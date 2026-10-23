import ArgumentParser
import BiRefNetCore
import Foundation

// 不用 @main + ParsableCommand.main()：ArgumentParser 默认把参数错误映射成 64，
// 而 PRD BR-09 要求参数错误退出码 2、运行错误 1
let arguments = Array(CommandLine.arguments.dropFirst())

let command: MatteCommand
do {
    command = try MatteCommand.parse(arguments)
} catch {
    // ArgumentParser 把帮助/版本请求也作为错误抛出（ParserError 是 internal，
    // 外部无法按类型判断），只能看用户是否显式要了帮助，这类情况按 0 退出
    let requestedHelp = arguments.contains { ["-h", "--help", "--version"].contains($0) }
    let text = MatteCommand.fullMessage(for: error)
    if requestedHelp {
        print(text)
        exit(0)
    }
    FileHandle.standardError.write(Data((text + "\n").utf8))
    exit(2)
}

do {
    try command.run()
    exit(0)
} catch let failure as CommandFailure {
    FileHandle.standardError.write(Data(("错误：\(failure.error.userMessage)\n").utf8))
    exit(failure.exitCode)
} catch {
    FileHandle.standardError.write(Data(("错误：\(String(describing: error))\n").utf8))
    exit(1)
}
