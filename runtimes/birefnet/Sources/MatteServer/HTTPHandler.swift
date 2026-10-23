import BiRefNetCore
import Foundation
import NIOCore
import NIOFoundationCompat
import NIOHTTP1
import os

/// HTTP 路由与请求校验。
///
/// 事件循环线程只做字节校验、路由和响应写回；解码、推理、编码都交给 MattingService（PRD BR-46）。
final class HTTPHandler: ChannelInboundHandler, @unchecked Sendable {
    typealias InboundIn = HTTPServerRequestPart
    typealias OutboundOut = HTTPServerResponsePart

    private static let logger = Logger(subsystem: "com.mlxforge.birefnet", category: "http")

    private let service: MattingService
    private let config: ServerConfig
    private let localAddresses: Set<String>

    private var head: HTTPRequestHead?
    private var body = ByteBuffer()
    private var rejected = false

    init(service: MattingService, config: ServerConfig) {
        self.service = service
        self.config = config
        self.localAddresses = SystemInfo.localIPv4Addresses()
    }

    func channelRead(context: ChannelHandlerContext, data: NIOAny) {
        switch unwrapInboundIn(data) {
        case .head(let head):
            self.head = head
            body.clear()
            rejected = false

            guard HTTPUtils.hostAllowed(
                head.headers,
                listenHost: config.host,
                localAddresses: localAddresses
            ) else {
                rejected = true
                sendError(
                    context: context,
                    status: .badRequest,
                    message: "Host 头不受信任",
                    close: true
                )
                return
            }

            if let issue = precheck(head) {
                rejected = true
                sendError(
                    context: context,
                    status: issue.status,
                    message: issue.message,
                    close: true
                )
            }

        case .body(var chunk):
            guard !rejected else { return }
            // 超过上限直接 413，不再解析正文（PRD BR-12）
            if body.readableBytes + chunk.readableBytes > ImageLimits.default.maxBytes {
                rejected = true
                sendError(
                    context: context,
                    status: .payloadTooLarge,
                    message: MattingError.payloadTooLarge.userMessage,
                    close: true
                )
                return
            }
            body.writeBuffer(&chunk)

        case .end:
            guard !rejected, let head else { return }
            route(context: context, head: head)
        }
    }

    /// 能在读完正文前判定的问题在这里拒绝
    private func precheck(_ head: HTTPRequestHead) -> (status: HTTPResponseStatus, message: String)? {
        let (path, _) = HTTPUtils.parseURI(head.uri)
        switch path {
        case "/v1/images/matting":
            guard head.method == .POST else {
                return (.methodNotAllowed, "该接口只接受 POST")
            }
            guard HTTPUtils.imageContentType(head.headers) != nil else {
                return (.unsupportedMediaType, MattingError.unsupportedFormat.userMessage)
            }
        case "/health", "/v1/models":
            guard head.method == .GET else {
                return (.methodNotAllowed, "该接口只接受 GET")
            }
        default:
            break
        }
        return nil
    }

    private func route(context: ChannelHandlerContext, head: HTTPRequestHead) {
        let (path, query) = HTTPUtils.parseURI(head.uri)
        switch path {
        case "/health":
            handleHealth(context: context)
        case "/v1/models":
            handleModels(context: context)
        case "/v1/images/matting":
            handleMatting(context: context, query: query)
        default:
            guard head.method == .GET || head.method == .HEAD else {
                sendError(
                    context: context,
                    status: .methodNotAllowed,
                    message: "该路径不接受该请求方法"
                )
                return
            }
            serveStatic(context: context, head: head, path: path, query: query)
        }
    }

    // MARK: - 抠图

    private func handleMatting(context: ChannelHandlerContext, query: [String: String]) {
        let mode: OutputMode
        if let raw = query["output"] {
            guard let parsed = OutputMode(rawValue: raw) else {
                sendError(
                    context: context,
                    status: .badRequest,
                    message: "output 只接受 cutout 或 mask"
                )
                return
            }
            mode = parsed
        } else {
            mode = .cutout
        }

        guard let data = body.readData(length: body.readableBytes), !data.isEmpty else {
            sendError(context: context, status: .badRequest, message: "请求体为空")
            return
        }

        let requestID = UUID().uuidString
        let started = Date()
        let service = self.service

        Task {
            do {
                let result = try await service.submit(data, mode: mode, requestID: requestID)
                let elapsed = Int(Date().timeIntervalSince(started) * 1000)
                context.eventLoop.execute {
                    self.sendMatte(
                        context: context,
                        result: result,
                        mode: mode,
                        requestID: requestID,
                        elapsedMs: elapsed
                    )
                }
            } catch let error as MattingError {
                context.eventLoop.execute {
                    self.sendError(
                        context: context,
                        status: ErrorMapping.status(for: error),
                        message: error.userMessage
                    )
                }
            } catch {
                Self.logger.error("未分类请求异常：\(String(describing: error), privacy: .public)")
                context.eventLoop.execute {
                    self.sendError(
                        context: context,
                        status: .internalServerError,
                        message: MattingError.inferenceFailed.userMessage
                    )
                }
            }
        }
    }

    private func sendMatte(
        context: ChannelHandlerContext,
        result: MatteResult,
        mode: OutputMode,
        requestID: String,
        elapsedMs: Int
    ) {
        var headers = HTTPHeaders()
        headers.add(name: "content-type", value: "image/png")
        headers.add(name: "x-request-id", value: requestID)
        headers.add(name: "x-output-mode", value: mode.rawValue)
        headers.add(name: "x-image-width", value: String(result.width))
        headers.add(name: "x-image-height", value: String(result.height))
        headers.add(name: "x-elapsed-ms", value: String(elapsedMs))
        headers.add(
            name: "content-disposition",
            value: "attachment; filename=\"\(mode.filenamePrefix)-\(requestID).png\""
        )
        headers.add(name: "cache-control", value: "no-store")
        headers.add(name: "content-length", value: String(result.png.count))

        var buffer = context.channel.allocator.buffer(capacity: result.png.count)
        buffer.writeBytes(result.png)
        write(context: context, status: .ok, headers: headers, buffer: buffer)
    }

    // MARK: - 状态与模型列表

    private func handleHealth(context: ChannelHandlerContext) {
        let service = self.service
        let config = self.config
        Task {
            let snapshot = await service.health()
            var payload: [String: Any] = [
                "status": snapshot.state == .failed ? "degraded" : "ok",
                "state": snapshot.state.rawValue,
                "model_loaded": snapshot.loaded,
                "idle_seconds": snapshot.idleSeconds,
                "idle_timeout_seconds": Int(config.idleTimeout),
                "min_macos": config.minMacOS,
                "queue": [
                    "waiting": snapshot.queueDepth,
                    "in_flight": snapshot.inFlight
                ],
                "memory": SystemInfo.memoryJSON()
            ]
            if let lastError = snapshot.lastError {
                payload["last_error"] = lastError
            }
            let buffer = HTTPUtils.jsonBuffer(payload)
            context.eventLoop.execute {
                self.sendJSON(context: context, buffer: buffer)
            }
        }
    }

    private func handleModels(context: ChannelHandlerContext) {
        let service = self.service
        let config = self.config
        Task {
            let started = await service.startTime()
            let payload: [String: Any] = [
                "object": "list",
                "data": [
                    [
                        "id": config.modelID,
                        "object": "model",
                        "created": Int(started.timeIntervalSince1970),
                        "owned_by": "mlxforge"
                    ]
                ]
            ]
            let buffer = HTTPUtils.jsonBuffer(payload)
            context.eventLoop.execute {
                self.sendJSON(context: context, buffer: buffer)
            }
        }
    }

    // MARK: - 静态资源

    private func serveStatic(
        context: ChannelHandlerContext,
        head: HTTPRequestHead,
        path: String,
        query: [String: String]
    ) {
        let root = config.webRoot.standardizedFileURL
        guard FileManager.default.fileExists(atPath: root.path) else {
            sendError(
                context: context,
                status: .notFound,
                message: "Web UI 尚未构建，请先构建前端产物"
            )
            return
        }

        if path == "/" {
            let index = root.appendingPathComponent("index.html")
            guard FileManager.default.fileExists(atPath: index.path) else {
                sendError(
                    context: context,
                    status: .notFound,
                    message: "Web UI 尚未构建，请先构建前端产物"
                )
                return
            }
            // 单模型启动时直接进抠图页（PRD BR-37、BR-41）。
            // 已经带了 page 参数就不要再重定向，否则同一个 URL 会无限跳自己
            if query["page"] == nil {
                var headers = HTTPHeaders()
                headers.add(name: "location", value: "/?page=matting")
                headers.add(name: "cache-control", value: "no-store")
                write(
                    context: context,
                    status: .temporaryRedirect,
                    headers: headers,
                    buffer: nil
                )
                return
            }
            serveFile(context: context, head: head, file: index)
            return
        }

        let segments = path.split(separator: "/")
        guard !segments.contains(".."), !segments.contains(".") else {
            sendError(context: context, status: .notFound, message: "资源不存在")
            return
        }
        let file = segments.reduce(root) { $0.appendingPathComponent(String($1)) }
        // 规范化后必须仍在 webRoot 下，防止路径穿越
        guard file.standardizedFileURL.path.hasPrefix(root.path + "/") else {
            sendError(context: context, status: .notFound, message: "资源不存在")
            return
        }
        serveFile(context: context, head: head, file: file)
    }

    /// 输出一个静态文件；HEAD 只回头部，不读文件内容
    private func serveFile(
        context: ChannelHandlerContext,
        head: HTTPRequestHead,
        file: URL
    ) {
        var headers = HTTPHeaders()
        headers.add(
            name: "content-type",
            value: HTTPUtils.mimeType(forPathExtension: file.pathExtension)
        )
        headers.add(name: "cache-control", value: "no-cache")

        if head.method == .HEAD {
            if let size = try? FileManager.default.attributesOfItem(atPath: file.path)[.size] as? Int {
                headers.add(name: "content-length", value: String(size))
            }
            write(context: context, status: .ok, headers: headers, buffer: nil)
            return
        }

        guard let data = try? Data(contentsOf: file) else {
            sendError(context: context, status: .notFound, message: "资源不存在")
            return
        }
        headers.add(name: "content-length", value: String(data.count))
        var buffer = context.channel.allocator.buffer(capacity: data.count)
        buffer.writeBytes(data)
        write(context: context, status: .ok, headers: headers, buffer: buffer)
    }

    // MARK: - 响应写回

    private func sendJSON(context: ChannelHandlerContext, buffer: ByteBuffer) {
        var headers = HTTPHeaders()
        headers.add(name: "content-type", value: "application/json; charset=utf-8")
        headers.add(name: "cache-control", value: "no-store")
        headers.add(name: "content-length", value: String(buffer.readableBytes))
        write(context: context, status: .ok, headers: headers, buffer: buffer)
    }

    private func sendError(
        context: ChannelHandlerContext,
        status: HTTPResponseStatus,
        message: String,
        close: Bool = false
    ) {
        var headers = HTTPHeaders()
        headers.add(name: "content-type", value: "application/json; charset=utf-8")
        headers.add(name: "cache-control", value: "no-store")
        if status == .tooManyRequests {
            headers.add(name: "retry-after", value: "5")
        }
        let buffer = ErrorMapping.body(status: status, message: message)
        headers.add(name: "content-length", value: String(buffer.readableBytes))
        write(context: context, status: status, headers: headers, buffer: buffer, close: close)
    }

    private func write(
        context: ChannelHandlerContext,
        status: HTTPResponseStatus,
        headers: HTTPHeaders,
        buffer: ByteBuffer?,
        close: Bool = false
    ) {
        var responseHead = HTTPResponseHead(version: .http1_1, status: status, headers: headers)
        if close {
            responseHead.headers.replaceOrAdd(name: "connection", value: "close")
        }
        context.write(wrapOutboundOut(.head(responseHead)), promise: nil)
        if let buffer {
            context.write(wrapOutboundOut(.body(.byteBuffer(buffer))), promise: nil)
        }
        let future = context.writeAndFlush(wrapOutboundOut(.end(nil)))
        if close {
            future.whenComplete { _ in context.close(promise: nil) }
        }
    }
}
