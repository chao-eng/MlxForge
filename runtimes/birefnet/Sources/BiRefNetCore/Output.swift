import CoreGraphics
import Foundation
import ImageIO

/// 输出形态。v1 只有透明底和灰度遮罩两种（PRD BR-16）。
public enum OutputMode: String, CaseIterable, Sendable {
    case cutout
    case mask

    /// 下载文件名前缀，沿用 OpenAI 图片接口的命名习惯
    public var filenamePrefix: String {
        switch self {
        case .cutout: return "cutout"
        case .mask: return "matte"
        }
    }
}

public enum PNGEncoder {
    /// 把 CGImage 编码成 PNG 字节。v1 只出 PNG（PRD BR-18）。
    public static func encode(_ image: CGImage) throws -> Data {
        let buffer = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(
            buffer as CFMutableData,
            "public.png" as CFString,
            1,
            nil
        ) else {
            throw MattingError.encodeFailed
        }
        CGImageDestinationAddImage(destination, image, nil)
        guard CGImageDestinationFinalize(destination), buffer.length > 0 else {
            throw MattingError.encodeFailed
        }
        return buffer as Data
    }
}
