import ArgumentParser
import BiRefNetCore
import Foundation

extension OutputMode: ExpressibleByArgument {
    public init?(argument: String) {
        self.init(rawValue: argument)
    }

    public static var allValueStrings: [String] {
        allCases.map(\.rawValue)
    }
}

/// 单张图片抠图。
///
/// 标准输出只打印输出文件的绝对路径，其余信息写标准错误（PRD BR-09）。
struct MatteCommand: ParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "birefnet-cli",
        abstract: "对单张图片抠图，输出 PNG。",
        discussion: "成功时标准输出只打印输出文件绝对路径，日志写标准错误。"
    )

    @Option(name: .long, help: "输入图片路径，支持 PNG、JPEG、WebP。")
    var input: String

    @Option(name: .long, help: "输出 PNG 路径，扩展名必须是 .png。")
    var output: String

    @Option(name: .long, help: "输出形态：cutout（透明底）或 mask（灰度遮罩）。")
    var mode: OutputMode = .cutout

    @Option(name: .long, help: "权重目录或 model.safetensors 路径。")
    var weights: String = "models/birefnet/fp16"

    @Flag(name: .long, help: "输出尺寸、耗时等诊断信息。")
    var verbose: Bool = false

    func validate() throws {
        guard FileManager.default.isReadableFile(atPath: input) else {
            throw ValidationError("输入文件不存在或不可读：\(input)")
        }
        guard URL(fileURLWithPath: output).pathExtension.lowercased() == "png" else {
            throw ValidationError("输出文件扩展名必须是 .png")
        }
    }

    func run() throws {
        _ = verbose

        let source: SourceImage
        let pipeline = MattingPipeline(weightsPath: weights)
        do {
            source = try ImageDecoder.decode(file: URL(fileURLWithPath: input))
            log("图片 \(source.width)x\(source.height)")

            let loadStarted = Date()
            try pipeline.load()
            let loadSeconds = Date().timeIntervalSince(loadStarted)

            let matteStarted = Date()
            let png = try pipeline.matte(source, mode: mode, requestID: "cli")
            let matteSeconds = Date().timeIntervalSince(matteStarted)
            pipeline.release()

            let target = URL(fileURLWithPath: output).standardizedFileURL
            do {
                try FileManager.default.createDirectory(
                    at: target.deletingLastPathComponent(),
                    withIntermediateDirectories: true
                )
                try png.write(to: target)
            } catch {
                throw CommandFailure(error: .encodeFailed)
            }

            log(String(
                format: "加载 %.2fs，抠图 %.2fs，输出 %d KB",
                loadSeconds, matteSeconds, png.count / 1024
            ))
            // BR-09：成功时标准输出只有这一行
            print(target.path)
        } catch let error as MattingError {
            throw CommandFailure(error: error)
        }
    }

    private func log(_ text: String) {
        FileHandle.standardError.write(Data(("\(text)\n").utf8))
    }
}

/// CLI 自己的错误包装，把运行期错误和参数错误区分成不同退出码。
struct CommandFailure: Error {
    let error: MattingError

    var exitCode: Int32 {
        switch error {
        case .invalidArgument, .payloadTooLarge, .unsupportedFormat,
             .decodeFailed, .dimensionsTooLarge:
            return 2
        default:
            return 1
        }
    }
}
