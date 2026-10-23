import Foundation

/// 抠图流程的错误分类。
///
/// 只做分类和面向用户的说明，退出码和 HTTP 状态由各自的入口映射，
/// 这样 CLI 和服务端能共用同一套实现（PRD BR-08）。
/// 内部异常细节在抛出前写入日志，不放进错误本身，避免泄漏路径或堆栈。
public enum MattingError: Error {
    /// 参数或输入不合法，服务端映射 400，CLI 映射退出码 2
    case invalidArgument(String)
    /// 请求体超过字节上限，服务端映射 413
    case payloadTooLarge
    /// 图片格式不支持，服务端映射 415
    case unsupportedFormat
    /// 图片损坏、截断或无法解码，服务端映射 400
    case decodeFailed
    /// 解码后尺寸超过像素上限，服务端映射 400
    case dimensionsTooLarge
    /// 权重文件缺失，服务端映射 503
    case weightsMissing
    /// 模型加载失败，服务端映射 503
    case loadFailed
    /// 推理过程异常，服务端映射 500
    case inferenceFailed
    /// PNG 编码失败，服务端映射 500
    case encodeFailed
    /// 服务端排队已满，映射 429
    case queueFull
    /// 服务端排队超时，映射 429
    case queueTimeout
    /// 服务不可用，映射 503
    case unavailable
}

extension MattingError {
    /// 给用户看的中文说明。不包含路径、堆栈和内部细节（PRD BR-32）。
    public var userMessage: String {
        switch self {
        case .invalidArgument(let text): return text
        case .payloadTooLarge: return "图片超过 20MB 上限"
        case .unsupportedFormat: return "只支持 PNG、JPEG、WebP 图片"
        case .decodeFailed: return "图片无法解码，可能已损坏或格式不受支持"
        case .dimensionsTooLarge: return "图片尺寸超过上限，最长边不能超过 8192 像素，总像素不能超过 3200 万"
        case .weightsMissing: return "模型权重缺失，请先运行安装脚本"
        case .loadFailed: return "模型加载失败"
        case .inferenceFailed: return "抠图推理失败"
        case .encodeFailed: return "生成 PNG 失败"
        case .queueFull: return "当前请求过多，请稍后重试"
        case .queueTimeout: return "排队等待超时，请稍后重试"
        case .unavailable: return "服务暂不可用，请稍后重试"
        }
    }
}
