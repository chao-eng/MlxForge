import CoreGraphics
import Foundation
import ImageIO
import os

/// 图片输入上限。v1 取值来自 PRD BR-12、BR-13，压测后再调整。
public struct ImageLimits {
    public var maxBytes: Int
    public var maxEdge: Int
    public var maxPixels: Int

    public static let `default` = ImageLimits(
        maxBytes: 20 * 1024 * 1024,
        maxEdge: 8192,
        maxPixels: 32_000_000
    )

    public init(maxBytes: Int, maxEdge: Int, maxPixels: Int) {
        self.maxBytes = maxBytes
        self.maxEdge = maxEdge
        self.maxPixels = maxPixels
    }
}

/// 解码后的源图。
///
/// 像素已经完成 EXIF 方向归一和 sRGB 转换，RGB 为非预乘值，
/// 这样 cutout 输出可以直接沿用源图颜色（PRD BR-17）。
public struct SourceImage {
    public let width: Int
    public let height: Int
    /// 每像素 4 字节，顺序 R、G、B、A
    public let rgba: [UInt8]

    public init(width: Int, height: Int, rgba: [UInt8]) {
        self.width = width
        self.height = height
        self.rgba = rgba
    }
}

public enum ImageDecoder {
    private static let logger = Logger(subsystem: "com.mlxforge.birefnet", category: "image")

    /// 从文件解码。先看文件大小再读，避免把超大文件整个读进内存。
    public static func decode(file url: URL, limits: ImageLimits = .default) throws -> SourceImage {
        let attributes = try? FileManager.default.attributesOfItem(atPath: url.path)
        let size = (attributes?[.size] as? NSNumber)?.intValue ?? 0
        guard size > 0 else { throw MattingError.decodeFailed }
        guard size <= limits.maxBytes else { throw MattingError.payloadTooLarge }
        guard let data = try? Data(contentsOf: url, options: .mappedIfSafe) else {
            throw MattingError.invalidArgument("输入文件不可读")
        }
        return try decode(data, limits: limits)
    }

    /// 从内存中的图片字节解码，方向和色彩都在这里归一。
    public static func decode(_ data: Data, limits: ImageLimits = .default) throws -> SourceImage {
        guard data.count <= limits.maxBytes else { throw MattingError.payloadTooLarge }

        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
              let original = CGImageSourceCreateImageAtIndex(source, 0, nil)
        else {
            logger.error("ImageIO 无法解析输入字节")
            throw MattingError.decodeFailed
        }

        let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any]
        let pixelWidth = (properties?[kCGImagePropertyPixelWidth] as? Int) ?? original.width
        let pixelHeight = (properties?[kCGImagePropertyPixelHeight] as? Int) ?? original.height
        let orientation = CGImagePropertyOrientation(
            rawValue: (properties?[kCGImagePropertyOrientation] as? UInt32) ?? 1
        ) ?? .up

        // 左/右旋转 90° 的图片，方向归一后宽高互换
        let swapsAxes = orientation == .left || orientation == .leftMirrored
            || orientation == .right || orientation == .rightMirrored
        let width = swapsAxes ? pixelHeight : pixelWidth
        let height = swapsAxes ? pixelWidth : pixelHeight

        guard width > 0, height > 0 else { throw MattingError.decodeFailed }
        guard max(width, height) <= limits.maxEdge, width * height <= limits.maxPixels else {
            logger.error("图片尺寸 \(width, privacy: .public)x\(height, privacy: .public) 超过上限")
            throw MattingError.dimensionsTooLarge
        }

        guard let colorSpace = CGColorSpace(name: CGColorSpace.sRGB) else {
            throw MattingError.decodeFailed
        }
        // premultipliedLast 是 CGBitmapContext 唯一支持带 alpha 的排列，
        // 拿到像素后再手工还原成非预乘，供 cutout 使用
        let bitmapInfo = CGBitmapInfo.byteOrder32Big.rawValue
            | CGImageAlphaInfo.premultipliedLast.rawValue
        guard let context = CGContext(
            data: nil,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: width * 4,
            space: colorSpace,
            bitmapInfo: bitmapInfo
        ) else {
            throw MattingError.decodeFailed
        }

        context.interpolationQuality = .high

        // EXIF 方向通过上下文变换应用，而不是读方向标记后交给下游
        context.concatenate(
            orientationTransform(orientation, width: pixelWidth, height: pixelHeight)
        )
        context.draw(
            original,
            in: CGRect(x: 0, y: 0, width: pixelWidth, height: pixelHeight)
        )

        guard let raw = context.data else { throw MattingError.decodeFailed }
        var pixels = [UInt8](
            UnsafeBufferPointer(
                start: raw.assumingMemoryBound(to: UInt8.self),
                count: width * height * 4
            )
        )

        // CGContext 输出预乘 alpha，转回直通值；全透明像素没有可还原的颜色
        for offset in stride(from: 0, to: pixels.count, by: 4) {
            let alpha = pixels[offset + 3]
            if alpha == 255 { continue }
            if alpha == 0 {
                pixels[offset] = 0
                pixels[offset + 1] = 0
                pixels[offset + 2] = 0
                continue
            }
            let factor = 255.0 / Float(alpha)
            for channel in 0..<3 {
                let value = (Float(pixels[offset + channel]) * factor).rounded()
                pixels[offset + channel] = UInt8(min(255, value))
            }
        }

        return SourceImage(width: width, height: height, rgba: pixels)
    }

    /// 白底合成后的不透明图片。模型只看合成结果，原图 alpha 不当作主体透明度（PRD BR-15）。
    public static func opaqueImage(_ source: SourceImage) -> CGImage? {
        var pixels = [UInt8](repeating: 255, count: source.width * source.height * 3)
        for index in 0..<(source.width * source.height) {
            let alpha = UInt32(source.rgba[index * 4 + 3])
            let whiteWeight = 255 - alpha
            for channel in 0..<3 {
                let value = (UInt32(source.rgba[index * 4 + channel]) * alpha + 255 * whiteWeight) / 255
                pixels[index * 3 + channel] = UInt8(min(255, value))
            }
        }
        guard let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
              let provider = CGDataProvider(data: Data(pixels) as CFData)
        else { return nil }
        return CGImage(
            width: source.width,
            height: source.height,
            bitsPerComponent: 8,
            bitsPerPixel: 24,
            bytesPerRow: source.width * 3,
            space: colorSpace,
            bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue),
            provider: provider,
            decode: nil,
            shouldInterpolate: false,
            intent: .defaultIntent
        )
    }

    /// 标准 EXIF 方向到 CGContext 变换的映射。
    private static func orientationTransform(
        _ orientation: CGImagePropertyOrientation,
        width: Int,
        height: Int
    ) -> CGAffineTransform {
        var transform = CGAffineTransform.identity
        switch orientation {
        case .down, .downMirrored:
            transform = CGAffineTransform(translationX: CGFloat(width), y: CGFloat(height))
                .rotated(by: .pi)
        case .left, .leftMirrored:
            transform = CGAffineTransform(translationX: CGFloat(width), y: 0)
                .rotated(by: .pi / 2)
        case .right, .rightMirrored:
            transform = CGAffineTransform(translationX: 0, y: CGFloat(height))
                .rotated(by: -.pi / 2)
        case .up, .upMirrored:
            break
        @unknown default:
            break
        }
        switch orientation {
        case .upMirrored, .downMirrored:
            transform = transform.translatedBy(x: CGFloat(width), y: 0).scaledBy(x: -1, y: 1)
        case .leftMirrored, .rightMirrored:
            transform = transform.translatedBy(x: CGFloat(height), y: 0).scaledBy(x: -1, y: 1)
        default:
            break
        }
        return transform
    }
}
