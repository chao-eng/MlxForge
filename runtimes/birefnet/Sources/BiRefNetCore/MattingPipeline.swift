import CoreGraphics
import Foundation
import MLX
import MLXBiRefNet
import os

/// 抠图管线：加载权重、执行推理、按形态编码。
///
/// CLI 和服务端共用这一个入口（PRD BR-08），服务端只要保证同一时刻
/// 只有一个任务进 Metal 即可（BR-24），并发控制不放在这里。
public final class MattingPipeline {
    private static let logger = Logger(subsystem: "com.mlxforge.birefnet", category: "pipeline")

    private let weightsPath: String
    private let inputSize: Int
    private var pipeline: BiRefNetPipeline?

    public init(weightsPath: String, inputSize: Int? = nil) {
        self.weightsPath = weightsPath
        self.inputSize = inputSize ?? Self.inputSizeFromEnvironment()
    }

    /// 模型内部推理边长，默认 1024。峰值 footprint 随边长明显增长（1024² 约 5GB、
    /// 768² 约 3.4GB、512² 约 1.8GB），但 512² 在低对比人像上会把脸部和发际
    /// 留成大块半透明，实测不可接受，所以默认取 1024；内存紧张时用
    /// BIREFNET_INPUT_SIZE=768 或 512 覆盖，输出始终回到源分辨率
    private static func inputSizeFromEnvironment() -> Int {
        guard let raw = ProcessInfo.processInfo.environment["BIREFNET_INPUT_SIZE"],
              let value = Int(raw)
        else { return 1024 }
        // Swin 的 patch 是 4、窗口是 7，取 32 的倍数最稳
        guard value >= 256, value <= 2048, value % 32 == 0 else {
            logger.warning("BIREFNET_INPUT_SIZE=\(raw, privacy: .public) 不合法，回退 1024")
            return 1024
        }
        return value
    }

    public var isLoaded: Bool { pipeline != nil }

    /// 权重可以是目录或 model.safetensors 文件。
    public func load() throws {
        guard pipeline == nil else { return }

        // MLX 默认不限制 GPU 缓冲区缓存，释放的张量会一直留着等复用。
        // 实测一张 4096² 图能让缓存涨到近 10GB，对 16GB 机器太危险；
        // 这里按 256MB 封顶，只留跨请求复用的小缓冲，大张量用完即还
        Memory.cacheLimit = 256 << 20

        var isDirectory: ObjCBool = false
        let exists = FileManager.default.fileExists(
            atPath: weightsPath,
            isDirectory: &isDirectory
        )
        if exists, isDirectory.boolValue {
            let file = URL(fileURLWithPath: weightsPath)
                .appendingPathComponent("model.safetensors")
            guard FileManager.default.fileExists(atPath: file.path) else {
                Self.logger.error("权重目录里缺少 model.safetensors")
                throw MattingError.weightsMissing
            }
        } else if !exists {
            Self.logger.error("权重路径不存在")
            throw MattingError.weightsMissing
        }

        let started = Date()
        do {
            var config = BiRefNetConfig.swinLargeDefault
            config.inputSize = (inputSize, inputSize)
            pipeline = try BiRefNetPipeline.fromPretrained(
                weightsPath,
                dtype: .float16,
                config: config
            )
        } catch {
            // 上游错误里可能带本地路径，只写日志不回传
            Self.logger.error("加载权重失败：\(String(describing: error), privacy: .public)")
            throw MattingError.loadFailed
        }
        Self.logger.info(
            "权重加载完成，耗时 \(Date().timeIntervalSince(started), privacy: .public)s"
        )
    }

    /// 释放引用。MLX 的 GPU 缓存要调用方另外清理（PRD BR-29）。
    public func release() {
        pipeline = nil
    }

    /// 单张图片抠图，返回 PNG 字节。requestID 只用于日志串联，不影响行为。
    public func matte(
        _ source: SourceImage,
        mode: OutputMode,
        requestID: String = "-"
    ) throws -> Data {
        let requestStarted = Date()
        // 重置 MLX 峰值，日志里的 peak 就只反映本次请求，而不是进程启动以来的最大值
        Memory.peakMemory = 0

        guard let pipeline else {
            Self.logger.error("request=\(requestID, privacy: .public) 推理前模型尚未加载")
            throw MattingError.loadFailed
        }
        guard let input = ImageDecoder.opaqueImage(source) else {
            Self.logger.error("request=\(requestID, privacy: .public) 无法把源图合成到白底")
            throw MattingError.decodeFailed
        }

        Self.logger.info(
            "request=\(requestID, privacy: .public) 开始推理 source=\(source.width, privacy: .public)x\(source.height, privacy: .public) mode=\(mode.rawValue, privacy: .public) input=\(self.inputSize, privacy: .public)x\(self.inputSize, privacy: .public)"
        )

        let inferStarted = Date()
        // 上游 callAsFunction 内含 precondition，参数不合法会直接终止进程，
        // 这里只在已通过尺寸校验的图片上调用
        let prediction = pipeline(input)
        guard let mask = prediction.maskAtSource else {
            Self.logger.error("request=\(requestID, privacy: .public) 模型没有返回源分辨率掩码")
            throw MattingError.inferenceFailed
        }
        let inferMs = Int(Date().timeIntervalSince(inferStarted) * 1000)
        Self.logger.info(
            "request=\(requestID, privacy: .public) 推理完成 耗时=\(inferMs, privacy: .public)ms \(self.memoryLine(), privacy: .public)"
        )

        let png: Data
        switch mode {
        case .mask:
            let grayscale = try BiRefNet.renderGrayscale(mask: mask)
            png = try PNGEncoder.encode(grayscale)
        case .cutout:
            let alpha: [Float] = mask.asArray(Float.self)
            png = try composeCutout(source: source, alpha: alpha)
        }

        Self.logger.info(
            "request=\(requestID, privacy: .public) 请求完成 总耗时=\(Int(Date().timeIntervalSince(requestStarted) * 1000), privacy: .public)ms 输出=\(png.count, privacy: .public)字节 \(self.memoryLine(), privacy: .public)"
        )
        return png
    }

    /// MLX 内存读数，单位 MB；peak 是本次请求的峰值（进入时已重置）
    private func memoryLine() -> String {
        let mb = 1_048_576
        return "mlx_active=\(Memory.activeMemory / mb)MB mlx_peak=\(Memory.peakMemory / mb)MB mlx_cache=\(Memory.cacheMemory / mb)MB"
    }

    /// 源图 RGB 加模型 alpha 合成 RGBA PNG。alpha 直通，不做预乘（PRD BR-17、BR-21）。
    private func composeCutout(source: SourceImage, alpha: [Float]) throws -> Data {
        let pixelCount = source.width * source.height
        guard alpha.count == pixelCount else {
            Self.logger.error("掩码元素数与源图不一致")
            throw MattingError.inferenceFailed
        }

        var pixels = [UInt8](repeating: 0, count: pixelCount * 4)
        for index in 0..<pixelCount {
            let offset = index * 4
            pixels[offset] = source.rgba[offset]
            pixels[offset + 1] = source.rgba[offset + 1]
            pixels[offset + 2] = source.rgba[offset + 2]
            let value = min(1, max(0, alpha[index]))
            pixels[offset + 3] = UInt8((value * 255).rounded())
        }

        guard let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
              let provider = CGDataProvider(data: Data(pixels) as CFData),
              let image = CGImage(
                width: source.width,
                height: source.height,
                bitsPerComponent: 8,
                bitsPerPixel: 32,
                bytesPerRow: source.width * 4,
                space: colorSpace,
                // .last 表示非预乘 alpha，PNG 编码后才能保持直通值
                bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.last.rawValue),
                provider: provider,
                decode: nil,
                shouldInterpolate: false,
                intent: .defaultIntent
              )
        else {
            Self.logger.error("无法构造 RGBA 位图")
            throw MattingError.encodeFailed
        }

        return try PNGEncoder.encode(image)
    }
}
