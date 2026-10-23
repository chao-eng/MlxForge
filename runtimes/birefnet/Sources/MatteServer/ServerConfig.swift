import Foundation

/// 服务端运行配置，启动时固定，运行中不热更新（PRD BR-50）
struct ServerConfig {
    var host: String
    var port: Int
    var weightsPath: String
    var idleTimeout: TimeInterval
    var webRoot: URL

    let modelID = "BiRefNet-fp16"
    let minMacOS = "14"
}
