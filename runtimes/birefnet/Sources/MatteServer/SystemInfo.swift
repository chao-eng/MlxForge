import Darwin
import Foundation
import MLX

enum SystemInfo {
    /// 进程物理内存足迹，与活动监视器「内存」列口径一致，含 MLX 的 GPU 分配。
    /// 采集失败返回 nil（JSON 里输出 null）
    static func processFootprint() -> Int? {
        var info = task_vm_info_data_t()
        var count = mach_msg_type_number_t(
            MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<natural_t>.size
        )
        let result = withUnsafeMutablePointer(to: &info) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &count)
            }
        }
        guard result == KERN_SUCCESS else { return nil }
        return Int(info.phys_footprint)
    }

    /// 整机已用/总量，取 vm_statistics64 的 active + wired + compressor
    static func machineMemory() -> (used: Int?, total: Int?) {
        var stats = vm_statistics64()
        var count = mach_msg_type_number_t(
            MemoryLayout<vm_statistics64>.size / MemoryLayout<integer_t>.size
        )
        let result = withUnsafeMutablePointer(to: &stats) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                host_statistics64(mach_host_self(), HOST_VM_INFO64, $0, &count)
            }
        }
        let total = Int(ProcessInfo.processInfo.physicalMemory)
        guard result == KERN_SUCCESS else { return (nil, total) }
        let pageSize = UInt64(vm_kernel_page_size)
        let pages = UInt64(stats.active_count)
            + UInt64(stats.wire_count)
            + UInt64(stats.compressor_page_count)
        return (Int(pages * pageSize), total)
    }

    /// 本机所有 IPv4 地址，用于 Host 头放行（PRD BR-34）
    static func localIPv4Addresses() -> Set<String> {
        var addresses = Set<String>()
        var list: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&list) == 0, let first = list else { return addresses }
        defer { freeifaddrs(list) }

        var current: UnsafeMutablePointer<ifaddrs>? = first
        while let entry = current {
            defer { current = entry.pointee.ifa_next }
            guard let address = entry.pointee.ifa_addr,
                  address.pointee.sa_family == UInt8(AF_INET)
            else { continue }
            var text = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            let result = getnameinfo(
                address,
                socklen_t(address.pointee.sa_len),
                &text,
                socklen_t(text.count),
                nil,
                0,
                NI_NUMERICHOST
            )
            if result == 0 {
                addresses.insert(String(cString: text))
            }
        }
        return addresses
    }

    /// /health 的六项内存指标（MB）：MLX 活动/峰值/缓存、进程足迹、整机已用/总量
    static func memoryJSON() -> [String: Any] {
        let machine = machineMemory()
        return [
            "mlx_active_mb": megabytes(Memory.activeMemory) ?? NSNull(),
            "mlx_peak_mb": megabytes(Memory.peakMemory) ?? NSNull(),
            "mlx_cache_mb": megabytes(Memory.cacheMemory) ?? NSNull(),
            "footprint_mb": megabytes(processFootprint()) ?? NSNull(),
            "system_used_mb": megabytes(machine.used) ?? NSNull(),
            "system_total_mb": megabytes(machine.total) ?? NSNull()
        ]
    }

    /// 字节换算成 MB，保留一位小数；nil 原样传回，让调用方输出 null
    private static func megabytes(_ bytes: Int?) -> Double? {
        guard let bytes else { return nil }
        return (Double(bytes) / 1_048_576 * 10).rounded() / 10
    }
}
