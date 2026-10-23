import BiRefNetCore
import Foundation
import MLX
import os

struct MatteResult: Sendable {
    let png: Data
    let width: Int
    let height: Int
}

/// 排队条目由 actor 内创建，续体只在 actor 内读写
private final class QueuedRequest: @unchecked Sendable {
    let data: Data
    let mode: OutputMode
    let requestID: String
    let enqueuedAt: Date
    var continuation: CheckedContinuation<MatteResult, Error>?

    init(data: Data, mode: OutputMode, requestID: String) {
        self.data = data
        self.mode = mode
        self.requestID = requestID
        self.enqueuedAt = Date()
    }
}

/// 唯一持有模型和队列的 actor。
///
/// 推理是同步阻塞的，运行期间 actor 不会让出，因此同一时刻只有一个任务进 Metal（PRD BR-24）；
/// 解码、推理、PNG 编码都在这里完成，不占用 NIO 事件循环（BR-46）。
actor MattingService {
    /// 等待队列上限，不含在途任务（PRD BR-25）
    static let waitingLimit = 8
    /// 排队超时（PRD BR-26）
    static let queueLimit: TimeInterval = 120
    /// 加载失败后的冷却时间（PRD BR-30）
    static let loadCooldown: TimeInterval = 5

    private static let logger = Logger(subsystem: "com.mlxforge.birefnet", category: "service")

    private let weightsPath: String
    private let idleTimeout: TimeInterval
    private let startedAt: Date

    private var pipeline: MattingPipeline?
    private var queue: [QueuedRequest] = []
    private var busy = false
    private var state: ModelState = .unloaded
    private var lastActive: Date
    private var cooldownUntil: Date?
    private var lastError: String?

    init(weightsPath: String, idleTimeout: TimeInterval) {
        self.weightsPath = weightsPath
        self.idleTimeout = idleTimeout
        self.startedAt = Date()
        self.lastActive = Date()
    }

    func startTime() -> Date { startedAt }

    func submit(_ data: Data, mode: OutputMode, requestID: String) async throws -> MatteResult {
        if queue.count >= Self.waitingLimit {
            Self.logger.warning(
                "request=\(requestID, privacy: .public) 队列已满，直接拒绝 队列=\(self.queue.count, privacy: .public)"
            )
            throw MattingError.queueFull
        }
        if let until = cooldownUntil, Date() < until { throw MattingError.unavailable }

        let request = QueuedRequest(data: data, mode: mode, requestID: requestID)
        Self.logger.info(
            "request=\(requestID, privacy: .public) 入队 mode=\(mode.rawValue, privacy: .public) 字节=\(data.count, privacy: .public) 队列=\(self.queue.count, privacy: .public) 在途=\(self.busy, privacy: .public)"
        )
        return try await withCheckedThrowingContinuation { continuation in
            request.continuation = continuation
            queue.append(request)
            if !busy {
                busy = true
                Task { await self.runLoop() }
            }
        }
    }

    func health() -> HealthSnapshot {
        HealthSnapshot(
            state: state,
            loaded: pipeline != nil,
            idleSeconds: Date().timeIntervalSince(lastActive),
            queueDepth: queue.count,
            inFlight: busy,
            lastError: lastError
        )
    }

    /// 由空闲计时器每 10 秒调用一次：清理过期排队，必要时卸载模型。
    func inspect() {
        purgeExpired()
        guard idleTimeout > 0, !busy, queue.isEmpty, pipeline != nil else { return }
        guard Date().timeIntervalSince(lastActive) >= idleTimeout else { return }

        state = .unloading
        pipeline?.release()
        pipeline = nil
        Memory.clearCache()
        state = .unloaded
        lastError = nil
        Self.logger.info("空闲达到阈值，已卸载模型并清理 GPU 缓存")
    }

    /// 优雅退出：未开始的排队直接失败，返回是否还有在途任务。
    func stopAccepting() -> Bool {
        for request in queue {
            request.continuation?.resume(throwing: MattingError.unavailable)
            request.continuation = nil
        }
        queue.removeAll()
        return busy
    }

    func releaseModel() {
        pipeline?.release()
        pipeline = nil
        Memory.clearCache()
        state = .unloaded
    }

    private func runLoop() async {
        while !queue.isEmpty {
            let request = queue.removeFirst()
            // 出队与超时判断在同一临界区完成（PRD BR-26）
            if Date().timeIntervalSince(request.enqueuedAt) > Self.queueLimit {
                Self.logger.error(
                    "request=\(request.requestID, privacy: .public) 排队超过 \(Self.queueLimit, privacy: .public)s，拒绝"
                )
                request.continuation?.resume(throwing: MattingError.queueTimeout)
                request.continuation = nil
                continue
            }
            Self.logger.info(
                "request=\(request.requestID, privacy: .public) 出队 排队等待=\(Int(Date().timeIntervalSince(request.enqueuedAt) * 1000), privacy: .public)ms 剩余队列=\(self.queue.count, privacy: .public)"
            )

            do {
                let result = try matte(request)
                Self.logger.info(
                    "request=\(request.requestID, privacy: .public) 队列总耗时=\(Int(Date().timeIntervalSince(request.enqueuedAt) * 1000), privacy: .public)ms 输出=\(result.png.count, privacy: .public)字节"
                )
                request.continuation?.resume(returning: result)
            } catch let error as MattingError {
                Self.logger.error(
                    "request=\(request.requestID, privacy: .public) 失败 耗时=\(Int(Date().timeIntervalSince(request.enqueuedAt) * 1000), privacy: .public)ms 原因=\(error.userMessage, privacy: .public)"
                )
                request.continuation?.resume(throwing: error)
            } catch {
                Self.logger.error(
                    "request=\(request.requestID, privacy: .public) 未分类的推理异常：\(String(describing: error), privacy: .public)"
                )
                request.continuation?.resume(throwing: MattingError.inferenceFailed)
            }
            request.continuation = nil
            lastActive = Date()
        }
        busy = false
    }

    private func purgeExpired() {
        let now = Date()
        var expired: [QueuedRequest] = []
        var kept: [QueuedRequest] = []
        for request in queue {
            if now.timeIntervalSince(request.enqueuedAt) > Self.queueLimit {
                expired.append(request)
            } else {
                kept.append(request)
            }
        }
        guard !expired.isEmpty else { return }
        queue = kept
        for request in expired {
            request.continuation?.resume(throwing: MattingError.queueTimeout)
            request.continuation = nil
        }
    }

    /// 同步执行，返回前不会让出 actor，保证串行
    private func matte(_ request: QueuedRequest) throws -> MatteResult {
        let decodeStarted = Date()
        let source = try ImageDecoder.decode(request.data)
        Self.logger.info(
            "request=\(request.requestID, privacy: .public) 解码完成 source=\(source.width, privacy: .public)x\(source.height, privacy: .public) 耗时=\(Int(Date().timeIntervalSince(decodeStarted) * 1000), privacy: .public)ms"
        )
        try ensureLoaded()

        state = .generating
        defer { state = .ready }
        let png = try pipeline!.matte(
            source,
            mode: request.mode,
            requestID: request.requestID
        )
        return MatteResult(png: png, width: source.width, height: source.height)
    }

    private func ensureLoaded() throws {
        if pipeline != nil {
            state = .ready
            return
        }
        if let until = cooldownUntil, Date() < until { throw MattingError.unavailable }

        state = .loading
        let candidate = MattingPipeline(weightsPath: weightsPath)
        do {
            try candidate.load()
        } catch let error as MattingError {
            state = .failed
            cooldownUntil = Date().addingTimeInterval(Self.loadCooldown)
            lastError = error.userMessage
            Self.logger.error("模型加载失败，进入冷却：\(error.userMessage, privacy: .public)")
            throw error
        }
        pipeline = candidate
        state = .ready
        cooldownUntil = nil
        lastError = nil
    }
}
