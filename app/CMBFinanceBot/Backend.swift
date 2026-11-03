import Foundation

struct Backend {
    let root: String
    let python: String
    private func timeout(for args: [String]) -> TimeInterval {
        switch args.first {
        case "emulator": return args.contains("start") ? 60 : 30
        case "cancel": return 300
        case "buy": return 420
        default: return 30
        }
    }
    func run(_ args: [String], input: [String: String]? = nil) async throws -> [String: Any] {
        let payload = try input.map { try JSONSerialization.data(withJSONObject: $0) }
        return try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let process = Process(), output = Pipe(), errors = Pipe(), stdin = Pipe()
                process.executableURL = URL(fileURLWithPath: python)
                process.arguments = ["-B", "src/admin_cli.py"] + args
                process.currentDirectoryURL = URL(fileURLWithPath: root)
                process.standardOutput = output
                process.standardError = errors
                process.standardInput = stdin
                // Drain both pipes while running, so verbose dependencies cannot block the child.
                let group = DispatchGroup()
                let captured = Capture()
                do {
                    try process.run()
                    group.enter()
                    DispatchQueue.global().async {
                        captured.data = output.fileHandleForReading.readDataToEndOfFile()
                        group.leave()
                    }
                    group.enter()
                    DispatchQueue.global().async {
                        _ = errors.fileHandleForReading.readDataToEndOfFile()
                        group.leave()
                    }
                    if let payload { try stdin.fileHandleForWriting.write(contentsOf: payload) }
                    try stdin.fileHandleForWriting.close()
                    let deadline = Date().addingTimeInterval(timeout(for: args))
                    while process.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.05) }
                    if process.isRunning {
                        process.terminate()
                        Thread.sleep(forTimeInterval: 0.3)
                        if process.isRunning { kill(process.processIdentifier, SIGKILL) }
                        process.waitUntilExit()
                        group.wait()
                        throw BackendError.message("操作超时，请刷新状态后再决定下一步。")
                    }
                    process.waitUntilExit()
                    group.wait()
                    guard let json = try JSONSerialization.jsonObject(with: captured.data) as? [String: Any] else {
                        throw BackendError.message("后端返回格式无效。")
                    }
                    guard process.terminationStatus == 0, json["ok"] as? Bool == true else {
                        throw BackendError.message(json["error"] as? String ?? "操作失败。")
                    }
                    continuation.resume(returning: json)
                } catch { continuation.resume(throwing: error) }
            }
        }
    }
}
final class Capture: @unchecked Sendable { var data = Data() }
enum BackendError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let s) = self { return s }; return nil }
}
