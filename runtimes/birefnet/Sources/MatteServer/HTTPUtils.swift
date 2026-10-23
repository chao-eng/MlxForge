import BiRefNetCore
import Foundation
import NIOCore
import NIOHTTP1

/// JSON 错误响应统一成 `{"error": {"type": ..., "message": ...}}`（PRD BR-32）
enum ErrorMapping {
    static func type(for status: HTTPResponseStatus) -> String {
        switch status {
        case .badRequest, .payloadTooLarge, .unsupportedMediaType:
            return "invalid_request_error"
        case .notFound:
            return "not_found_error"
        case .methodNotAllowed:
            return "method_not_allowed"
        case .tooManyRequests:
            return "rate_limit_error"
        case .serviceUnavailable:
            return "service_unavailable"
        default:
            return "server_error"
        }
    }

    static func status(for error: MattingError) -> HTTPResponseStatus {
        switch error {
        case .invalidArgument, .decodeFailed, .dimensionsTooLarge: return .badRequest
        case .payloadTooLarge: return .payloadTooLarge
        case .unsupportedFormat: return .unsupportedMediaType
        case .weightsMissing, .loadFailed, .unavailable: return .serviceUnavailable
        case .queueFull, .queueTimeout: return .tooManyRequests
        case .inferenceFailed, .encodeFailed: return .internalServerError
        }
    }

    static func body(status: HTTPResponseStatus, message: String) -> ByteBuffer {
        let payload: [String: Any] = [
            "error": [
                "type": type(for: status),
                "message": message
            ]
        ]
        return HTTPUtils.jsonBuffer(payload)
    }
}

enum HTTPUtils {
    static func jsonBuffer(_ object: [String: Any]) -> ByteBuffer {
        let data = (try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]))
            ?? Data("{}".utf8)
        var buffer = ByteBufferAllocator().buffer(capacity: data.count)
        buffer.writeBytes(data)
        return buffer
    }

    /// 请求 URI 拆成路径和查询参数
    static func parseURI(_ uri: String) -> (path: String, query: [String: String]) {
        let parts = uri.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false)
        let path = parts.first.map(String.init) ?? "/"
        var query: [String: String] = [:]
        if parts.count > 1 {
            for item in parts[1].split(separator: "&") {
                let pair = item.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
                let key = String(pair[0]).removingPercentEncoding ?? String(pair[0])
                let value = pair.count > 1
                    ? (String(pair[1]).removingPercentEncoding ?? String(pair[1]))
                    : ""
                query[key] = value
            }
        }
        return (path, query)
    }

    /// Content-Type 只认三种图片类型，忽略参数部分（PRD BR-11）
    static func imageContentType(_ headers: HTTPHeaders) -> String? {
        guard let value = headers.first(name: "content-type") else { return nil }
        let type = value.split(separator: ";").first.map {
            $0.trimmingCharacters(in: .whitespaces)
        }
        switch type?.lowercased() {
        case "image/png", "image/jpeg", "image/webp":
            return type
        default:
            return nil
        }
    }

    /// Host 头校验：只放行回环、监听地址、本机地址和 .local 主机名（PRD BR-34）
    static func hostAllowed(
        _ headers: HTTPHeaders,
        listenHost: String,
        localAddresses: Set<String>
    ) -> Bool {
        guard let raw = headers.first(name: "host"), !raw.isEmpty else { return false }
        var host = raw
        if let colon = host.lastIndex(of: ":"), !host.hasSuffix("]") {
            // 形如 127.0.0.1:8000；IPv6 字面量用 [] 包起来，不在这里切
            host = String(host[..<colon])
        }
        host = host
            .trimmingCharacters(in: CharacterSet(charactersIn: "[]"))
            .lowercased()
        if host == "localhost" || host == "::1" || host.hasPrefix("127.") {
            return true
        }
        if host == listenHost.lowercased() { return true }
        if host.hasSuffix(".local") { return true }
        if host == ProcessInfo.processInfo.hostName.lowercased() { return true }
        return localAddresses.contains(host)
    }

    static func mimeType(forPathExtension ext: String) -> String {
        switch ext.lowercased() {
        case "html": return "text/html; charset=utf-8"
        case "js", "mjs": return "text/javascript; charset=utf-8"
        case "css": return "text/css; charset=utf-8"
        case "json": return "application/json"
        case "png": return "image/png"
        case "jpg", "jpeg": return "image/jpeg"
        case "webp": return "image/webp"
        case "svg": return "image/svg+xml"
        case "ico": return "image/x-icon"
        case "woff2": return "font/woff2"
        default: return "application/octet-stream"
        }
    }
}
