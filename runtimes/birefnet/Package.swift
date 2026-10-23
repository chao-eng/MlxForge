// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "birefnet",
    platforms: [.macOS(.v14)],
    // 产物名和上游 mlx-swift-BiRefNet 的 birefnet-cli 重名会把文件写到同一路径并互相覆盖，
    // 所以本包用唯一名字，再由 scripts/build_birefnet.sh 软链回 PRD 约定的名字
    products: [
        .executable(name: "birefnet-matte-cli", targets: ["MatteCLI"]),
        .executable(name: "birefnet-matte-server", targets: ["MatteServer"])
    ],
    dependencies: [
        .package(url: "https://github.com/mnmly/mlx-swift-BiRefNet.git", exact: "0.1.1"),
        // 固定 0.31.4：0.31.5 起要求 Swift 6.3，当前工具链是 6.2.3（PRD BR-03）
        .package(url: "https://github.com/ml-explore/mlx-swift.git", exact: "0.31.4"),
        .package(url: "https://github.com/apple/swift-argument-parser.git", from: "1.3.0"),
        .package(url: "https://github.com/apple/swift-nio.git", from: "2.60.0")
    ],
    targets: [
        .target(
            name: "BiRefNetCore",
            dependencies: [
                .product(name: "MLXBiRefNet", package: "mlx-swift-BiRefNet"),
                .product(name: "MLX", package: "mlx-swift")
            ]
        ),
        .executableTarget(
            name: "MatteCLI",
            dependencies: [
                "BiRefNetCore",
                .product(name: "ArgumentParser", package: "swift-argument-parser")
            ]
        ),
        .executableTarget(
            name: "MatteServer",
            dependencies: [
                "BiRefNetCore",
                .product(name: "ArgumentParser", package: "swift-argument-parser"),
                .product(name: "NIOCore", package: "swift-nio"),
                .product(name: "NIOPosix", package: "swift-nio"),
                .product(name: "NIOHTTP1", package: "swift-nio"),
                .product(name: "NIOFoundationCompat", package: "swift-nio")
            ]
        )
    ]
)
