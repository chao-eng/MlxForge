import ArgumentParser
import Foundation
import NIOCore
import NIOHTTP1
import NIOPosix
import os

struct ServerOptions: ParsableArguments {
    @Option(name: .long, help: "监听地址，默认 127.0.0.1。")
    var host: String = "127.0.0.1"

    @Option(name: .long, help: "监听端口，默认 8000，被占用时直接报错。")
    var port: Int = 8000

    @Option(name: .long, help: "权重目录或 model.safetensors 路径。")
    var weights: String = "models/birefnet/fp16"

    @Option(name: .long, help: "空闲多少秒后卸载模型，0 表示常驻。")
    var idleTimeout: Int?

    @Option(name: .long, help: "前端产物目录，默认 web/dist。")
    var webRoot: String = "web/dist"
}

let logger = Logger(subsystem: "com.mlxforge.birefnet", category: "main")

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data(("错误：\(message)\n").utf8))
    exit(1)
}

let options: ServerOptions
do {
    options = try ServerOptions.parse(Array(CommandLine.arguments.dropFirst()))
} catch let cleanExit as CleanExit {
    print(cleanExit)
    exit(0)
} catch {
    FileHandle.standardError.write(Data(("\(error)\n").utf8))
    exit(2)
}

guard (1...65535).contains(options.port) else {
    FileHandle.standardError.write(Data(("错误：--port 必须在 1~65535 之间\n").utf8))
    exit(2)
}

let environment = ProcessInfo.processInfo.environment
let envIdle = environment["BIREFNET_IDLE_TIMEOUT"].flatMap(Int.init)
let idleTimeout = options.idleTimeout ?? envIdle ?? 1200
guard idleTimeout >= 0 else {
    FileHandle.standardError.write(Data(("错误：空闲超时不能为负数\n").utf8))
    exit(2)
}

// 默认只监听回环地址，非回环必须显式授权（PRD BR-33）
let loopbackHosts = ["127.0.0.1", "localhost", "::1"]
if !loopbackHosts.contains(options.host.lowercased()),
   environment["BIREFNET_ALLOW_REMOTE"] != "1" {
    fail("非回环地址需要设置 BIREFNET_ALLOW_REMOTE=1 才能监听")
}

let config = ServerConfig(
    host: options.host,
    port: options.port,
    weightsPath: options.weights,
    idleTimeout: TimeInterval(idleTimeout),
    webRoot: URL(fileURLWithPath: options.webRoot)
)

let service = MattingService(
    weightsPath: config.weightsPath,
    idleTimeout: config.idleTimeout
)

// 启动信息记到 logs/birefnet.log，方便启动脚本和排障对时间线（PRD UC-03）
func appendStartupLog() {
    let path = environment["BIREFNET_LOG"] ?? "logs/birefnet.log"
    let url = URL(fileURLWithPath: path)
    let formatter = ISO8601DateFormatter()
    let line = [
        formatter.string(from: Date()),
        "启动",
        "host=\(config.host)",
        "port=\(config.port)",
        "idle_timeout=\(Int(config.idleTimeout))",
        "pid=\(ProcessInfo.processInfo.processIdentifier)"
    ].joined(separator: " ") + "\n"

    do {
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        if !FileManager.default.fileExists(atPath: url.path) {
            FileManager.default.createFile(atPath: url.path, contents: nil)
        }
        let handle = try FileHandle(forWritingTo: url)
        try handle.seekToEnd()
        handle.write(Data(line.utf8))
        try handle.close()
    } catch {
        logger.error("写入启动日志失败：\(String(describing: error), privacy: .public)")
    }
}

appendStartupLog()

let group = MultiThreadedEventLoopGroup(numberOfThreads: System.coreCount)
let bootstrap = ServerBootstrap(group: group)
    .serverChannelOption(ChannelOptions.backlog, value: 256)
    .serverChannelOption(ChannelOptions.socketOption(.so_reuseaddr), value: 1)
    .childChannelOption(ChannelOptions.socketOption(.so_reuseaddr), value: 1)
    .childChannelOption(ChannelOptions.maxMessagesPerRead, value: 16)
    .childChannelInitializer { channel in
        channel.pipeline.addHandlers([
            HTTPResponseEncoder(),
            ByteToMessageHandler(HTTPRequestDecoder(leftOverBytesStrategy: .forwardBytes)),
            HTTPHandler(service: service, config: config)
        ])
    }

let channel: Channel
do {
    channel = try await bootstrap.bind(host: config.host, port: config.port).get()
} catch {
    fail("端口 \(config.port) 无法监听：\(String(describing: error))")
}

logger.info("服务已启动 http://\(config.host, privacy: .public):\(config.port, privacy: .public)")

// 每 10 秒巡检一次空闲和排队超时（PRD §4.6）
let timer = DispatchSource.makeTimerSource(queue: .global())
timer.schedule(deadline: .now() + 10, repeating: 10)
timer.setEventHandler {
    Task { await service.inspect() }
}
timer.resume()

// 收到 SIGTERM/SIGINT 后停止接新请求，等在途任务收尾（PRD BR-31）
signal(SIGTERM, SIG_IGN)
signal(SIGINT, SIG_IGN)
let shutdown = ShutdownFlag()
let terminateSource = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .global())
terminateSource.setEventHandler { shutdown.trigger() }
terminateSource.resume()
let interruptSource = DispatchSource.makeSignalSource(signal: SIGINT, queue: .global())
interruptSource.setEventHandler { shutdown.trigger() }
interruptSource.resume()

await shutdown.wait()

logger.info("收到退出信号，停止接收新请求")
_ = try? await channel.close().get()

let busy = await service.stopAccepting()
if busy {
    let deadline = Date().addingTimeInterval(120)
    while await service.health().inFlight, Date() < deadline {
        try? await Task.sleep(nanoseconds: 200_000_000)
    }
}

await service.releaseModel()
try? await group.shutdownGracefully()
exit(0)

/// 在信号回调和顶层 await 之间传一次退出通知
final class ShutdownFlag: @unchecked Sendable {
    private let lock = NSLock()
    private var completed = false
    private var continuation: CheckedContinuation<Void, Never>?

    func trigger() {
        lock.lock()
        guard !completed else {
            lock.unlock()
            return
        }
        completed = true
        let pending = continuation
        continuation = nil
        lock.unlock()
        pending?.resume()
    }

    func wait() async {
        await withCheckedContinuation { continuation in
            lock.lock()
            if completed {
                lock.unlock()
                continuation.resume()
            } else {
                self.continuation = continuation
                lock.unlock()
            }
        }
    }
}
