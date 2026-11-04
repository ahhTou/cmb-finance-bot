import SwiftUI
import AppKit
import UserNotifications

@MainActor final class Model: ObservableObject {
    @Published var status: [String: Any] = [:]
    @Published var device: [String: Any] = [:]
    @Published var system: [String: Any] = [:]
    @Published var history: [[String: Any]] = []
    @Published var historyTotal = 0
    @Published var favorites: [[String: Any]] = []
    @Published var logLines: [String] = []
    @Published var logPath = ""
    @Published var commandOutput: [String] = []
    @Published var screenshot: NSImage?
    @Published var message: String?
    @Published var busy = false
    @Published var busyLabel = ""
    @Published var windowVisible = true
    @Published var lastRefresh: Date?
    @Published var root = UserDefaults.standard.string(forKey: "projectRoot") ?? ""
    @Published var python = UserDefaults.standard.string(forKey: "python") ?? "/usr/bin/python3"
    var refreshing = false

    init() {
        Task { _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) }
    }

    var backend: Backend { Backend(root: root, python: python) }
    var task: [String: Any] { dictValue(status["task"]) }
    var phase: String { task["phase"] as? String ?? "未布防" }
    var active: Bool { ["armed", "preparing", "waiting", "firing"].contains(phase) }
    var running: Bool { boolValue(status["running"]) == true }
    var credentialsDisabled: Bool { ["preparing", "waiting", "firing"].contains(phase) }
    var credentialState: String {
        switch dictValue(status["credentials"])["state"] as? String {
        case "configured": return "已设置"
        case "invalid": return "格式无效"
        case "unavailable": return "未设置或无法读取"
        default: return "未知"
        }
    }
    var mailConfigured: Bool { boolValue(status["mail_configured"]) == true }
    var agent: String {
        let value = dictValue(status["agent"])
        switch value["state"] as? String {
        case "watching": return "监听中 · \(value["session"] ?? "") · \(value["last_seen"] ?? "")"
        case "stale": return "Agent 失联"
        default: return "无 Agent 监听"
        }
    }
    var agentShort: String {
        switch dictValue(status["agent"])["state"] as? String {
        case "watching": return "监听中"
        case "stale": return "已失联"
        default: return "未监听"
        }
    }
    var lastRefreshText: String {
        guard let lastRefresh else { return "尚未刷新" }
        return lastRefresh.formatted(date: .omitted, time: .standard)
    }

    func saveSettings() {
        UserDefaults.standard.set(root, forKey: "projectRoot")
        UserDefaults.standard.set(python, forKey: "python")
        Task { await refresh() }
    }

    func chooseProject() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        if panel.runModal() == .OK, let url = panel.url {
            root = url.path
            saveSettings()
        }
    }

    func refresh() async {
        guard !root.isEmpty, !refreshing else { return }
        refreshing = true
        defer { refreshing = false }
        do {
            let previous = phase
            status = try await backend.run(["status"])
            favorites = arrayValue(status["favorites"])
            lastRefresh = Date()
            if previous != phase && previous != "未布防" {
                let content = UNMutableNotificationContent()
                content.title = "招行理财值守"
                content.body = "阶段：\(phase) · \(Date().formatted(date: .omitted, time: .standard))"
                try? await UNUserNotificationCenter.current().add(
                    UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
            }
        } catch {
            message = error.localizedDescription
        }
    }

    func loadDashboard() async {
        guard !root.isEmpty, !busy else { return }
        busy = true
        busyLabel = "刷新状态"
        defer { busy = false; busyLabel = "" }
        await refresh()
        do { device = try await backend.run(["device"]) }
        catch { if message == nil { message = error.localizedDescription } }
        do { system = try await backend.run(["system"]) }
        catch { if message == nil { message = error.localizedDescription } }
    }

    func loadDevice() async {
        guard !root.isEmpty, !busy else { return }
        busy = true
        busyLabel = "刷新设备"
        defer { busy = false; busyLabel = "" }
        do { device = try await backend.run(["device"]) }
        catch { message = error.localizedDescription }
    }

    func loadHistory() async {
        guard !root.isEmpty, !busy else { return }
        busy = true
        busyLabel = "加载历史"
        defer { busy = false; busyLabel = "" }
        do {
            let result = try await backend.run(["history"])
            history = arrayValue(result["records"])
            historyTotal = (result["total"] as? NSNumber)?.intValue ?? history.count
            if let path = result["log_path"] as? String { logPath = path }
            let log = try await backend.run(["log", "--lines", "800"])
            logLines = log["lines"] as? [String] ?? []
            if let path = log["path"] as? String { logPath = path }
        } catch {
            message = error.localizedDescription
        }
    }

    func loadLog() async {
        guard !root.isEmpty else { return }
        do {
            let result = try await backend.run(["log", "--lines", "1200"])
            logLines = result["lines"] as? [String] ?? []
            if let path = result["path"] as? String { logPath = path }
        } catch {
            message = error.localizedDescription
        }
    }

    @discardableResult
    func action(_ args: [String], label: String? = nil, input: [String: String]? = nil,
                refreshAfter: Bool = true) async -> Bool {
        guard !root.isEmpty else { message = "请先选择项目目录。"; return false }
        guard !busy else { return false }
        busy = true
        busyLabel = label ?? actionLabel(args)
        message = nil
        if args.first == "cancel" || args.first == "buy" { commandOutput = [] }
        defer { busy = false; busyLabel = "" }
        do {
            let result = try await backend.run(args, input: input)
            apply(result, for: args)
            if refreshAfter { await refresh() }
            return true
        } catch {
            message = error.localizedDescription
            return false
        }
    }

    func refreshCurrent(_ tab: Int) async {
        guard !root.isEmpty else { return }
        switch tab {
        case 1: await loadDashboard()
        case 2:
            await refresh()
            await loadDevice()
        case 3: await refresh()
        case 4: await loadHistory()
        default: await refresh()
        }
    }

    func copyWatch() {
        guard !root.isEmpty else {
            message = "请先选择项目目录。"
            return
        }
        let path = URL(fileURLWithPath: (root as NSString).expandingTildeInPath, isDirectory: true)
            .appendingPathComponent("skills/cmb-watch/SKILL.md").standardizedFileURL.path
        guard FileManager.default.fileExists(atPath: path) else {
            message = "当前项目目录下没有找到监听 Skill。"
            return
        }
        copyText("读取项目 Skill「\(path)」，用 cmb-watch 监听当前布防。")
    }

    private func apply(_ result: [String: Any], for args: [String]) {
        switch args.first {
        case "device": device = result
        case "system": system = result
        case "history":
            history = arrayValue(result["records"])
            historyTotal = (result["total"] as? NSNumber)?.intValue ?? history.count
            if let path = result["log_path"] as? String { logPath = path }
        case "log":
            logLines = result["lines"] as? [String] ?? []
            if let path = result["path"] as? String { logPath = path }
        case "cancel", "buy":
            commandOutput = result["output"] as? [String] ?? []
        case "screenshot":
            if let path = result["path"] as? String { screenshot = NSImage(contentsOfFile: path) }
        default: break
        }
    }

    private func actionLabel(_ args: [String]) -> String {
        switch args.first {
        case "device": return "刷新设备"
        case "system": return "刷新系统"
        case "history": return "加载历史"
        case "log": return "加载日志"
        case "emulator": return args.contains("start") ? "启动模拟器" : "关闭模拟器"
        case "keep-awake": return "恢复常亮"
        case "screenshot": return "截取画面"
        case "arm": return "布防"
        case "disarm": return "取消布防"
        case "cancel": return "撤单"
        case "buy": return args.contains("--confirm-real-payment") ? "真实单笔购买" : "演练购买"
        case "set-login-pattern", "set-payment-password": return "保存凭据"
        case "agent-heartbeat": return "更新心跳"
        default: return "处理中"
        }
    }
}
