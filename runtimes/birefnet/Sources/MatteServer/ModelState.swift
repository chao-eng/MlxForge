import Foundation

/// 只允许这六个状态（PRD BR-23、§4.4）
enum ModelState: String, Sendable {
    case unloaded
    case loading
    case ready
    case generating
    case unloading
    case failed
}

/// /health 的快照，所有字段都在 actor 内取，避免读到半更新状态
struct HealthSnapshot: Sendable {
    let state: ModelState
    let loaded: Bool
    let idleSeconds: Double
    let queueDepth: Int
    let inFlight: Bool
    let lastError: String?
}
