import SwiftUI
import AppKit
import UserNotifications

@MainActor final class Model: ObservableObject {
    @Published var status: [String: Any] = [:]
    @Published var device: [String: Any] = [:]
    @Published var system: [String: Any] = [:]
    @Published var history: [[String: Any]] = []
    @Published var screenshot: NSImage?
    @Published var message: String?
    @Published var busy = false
    @Published var root = UserDefaults.standard.string(forKey: "projectRoot") ?? ""
    @Published var python = UserDefaults.standard.string(forKey: "python") ?? "/usr/bin/python3"
    var refreshing = false
    private var polling: Task<Void, Never>?
    init() {
        polling = Task { [weak self] in
            _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])
            while !Task.isCancelled {
                await self?.refresh()
                try? await Task.sleep(nanoseconds: 60_000_000_000)
            }
        }
    }
    var backend: Backend { Backend(root: root, python: python) }
    var task: [String: Any] { status["task"] as? [String: Any] ?? [:] }
    var phase: String { task["phase"] as? String ?? "未布防" }
    var active: Bool { ["armed", "preparing", "firing"].contains(phase) }
    var credentialsDisabled: Bool { ["preparing", "firing"].contains(phase) }
    var agent: String {
        let a = status["agent"] as? [String: Any] ?? [:]
        switch a["state"] as? String {
        case "watching": return "监听中 · \(a["session"] ?? "") · \(a["last_seen"] ?? "")"
        case "stale": return "Agent 失联"
        default: return "无 Agent 监听"
        }
    }
    var credentialState: String {
        switch (status["credentials"] as? [String: Any])?["state"] as? String {
        case "configured": return "已设置"
        case "invalid": return "格式无效"
        case "unavailable": return "未设置或无法读取"
        default: return "未知"
        }
    }
    var icon: String {
        switch phase {
        case "armed": return "clock.badge.checkmark"
        case "preparing": return "arrow.triangle.2.circlepath"
        case "firing": return "bolt.fill"
        case "done": return "checkmark.circle"
        case "aborted": return "exclamationmark.triangle"
        default: return "moon"
        }
    }
    func saveSettings() {
        UserDefaults.standard.set(root, forKey: "projectRoot")
        UserDefaults.standard.set(python, forKey: "python")
        Task { await refresh() }
    }
    func chooseProject() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true; panel.canChooseFiles = false
        if panel.runModal() == .OK, let url = panel.url {
            root = url.path; saveSettings()
        }
    }
    func refresh() async {
        guard !root.isEmpty, !refreshing else { return }
        refreshing = true
        defer { refreshing = false }
        do {
            let previous = phase
            status = try await backend.run(["status"])
            if previous != phase && previous != "未布防" {
                let content = UNMutableNotificationContent()
                content.title = "招行理财值守"
                content.body = "阶段：\(phase) · \(Date().formatted(date: .omitted, time: .standard))"
                try? await UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
            }
        } catch { message = error.localizedDescription }
    }
    func action(_ args: [String], input: [String: String]? = nil) async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        do {
            let result = try await backend.run(args, input: input)
            if args == ["device"] { device = result }
            if args == ["system"] { system = result }
            if args == ["history"] { history = result["records"] as? [[String: Any]] ?? [] }
            if let path = result["path"] as? String { screenshot = NSImage(contentsOfFile: path) }
            await refresh()
        } catch { message = error.localizedDescription }
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
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString("读取项目 Skill「\(path)」，用 cmb-watch 监听当前布防。", forType: .string)
    }
}

@MainActor final class ManagementWindow: NSWindow {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
    override func performKeyEquivalent(with event: NSEvent) -> Bool {
        if event.modifierFlags.contains(.command), event.charactersIgnoringModifiers == "w" {
            NSApp.terminate(nil)
            return true
        }
        return super.performKeyEquivalent(with: event)
    }

    @objc func toggleZoom(_ sender: Any?) { zoom(sender) }

}

@MainActor final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private let model = Model()
    private var managementWindow: ManagementWindow?
    private var confirmingExit = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        installMenus()
        let view = ManagementView().environmentObject(model)
            .frame(minWidth: 940, minHeight: 680)
        let window = ManagementWindow(contentRect: NSRect(x: 0, y: 0, width: 1040, height: 760),
                                      styleMask: [.titled, .fullSizeContentView, .resizable, .closable, .miniaturizable],
                                      backing: .buffered, defer: false)
        window.title = "招行理财值守"
        window.identifier = NSUserInterfaceItemIdentifier("management")
        window.delegate = self
        window.contentView = NSHostingView(rootView: view)
        window.minSize = NSSize(width: 940, height: 680)
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.titlebarSeparatorStyle = .none
        window.toolbar = nil
        window.backgroundColor = NSColor(calibratedWhite: 30.0 / 255, alpha: 1)
        window.isOpaque = true
        window.isMovableByWindowBackground = true
        window.hasShadow = true
        window.isReleasedWhenClosed = false
        window.center()
        managementWindow = window
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func installMenus() {
        let main = NSMenu()
        let appItem = NSMenuItem()
        main.addItem(appItem)
        let appMenu = NSMenu(title: "招行理财值守")
        appMenu.addItem(withTitle: "隐藏招行理财值守", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "退出招行理财值守", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q").target = NSApp
        appItem.submenu = appMenu
        let editItem = NSMenuItem()
        main.addItem(editItem)
        let edit = NSMenu(title: "编辑")
        edit.addItem(withTitle: "撤销", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        let windowItem = NSMenuItem()
        main.addItem(windowItem)
        let windowMenu = NSMenu(title: "窗口")
        windowMenu.addItem(withTitle: "关闭窗口", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "w").target = NSApp
        windowMenu.addItem(withTitle: "最小化", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "缩放", action: #selector(ManagementWindow.toggleZoom(_:)), keyEquivalent: "")
        windowItem.submenu = windowMenu
        NSApp.mainMenu = main
        NSApp.windowsMenu = windowMenu
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        NSApp.terminate(nil)
        return false
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard !confirmingExit else { return .terminateCancel }
        confirmingExit = true
        defer { confirmingExit = false }
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = "关闭招行理财值守？"
        alert.informativeText = "关闭后将退出管理页面，停止界面刷新和阶段通知。已启动的值守任务仍会独立运行，不会自动取消。"
        alert.addButton(withTitle: "继续打开")
        alert.addButton(withTitle: "关闭并退出")
        alert.buttons[1].hasDestructiveAction = true
        return alert.runModal() == .alertSecondButtonReturn ? .terminateNow : .terminateCancel
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        managementWindow?.deminiaturize(nil)
        managementWindow?.makeKeyAndOrderFront(nil)
        sender.activate(ignoringOtherApps: true)
        return false
    }
}

@main struct CMBFinanceBotApp {
    @MainActor static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.accessory)
        withExtendedLifetime(delegate) { app.run() }
    }
}
private enum AppPalette {
    static let background = Color(white: 30.0 / 255)
    static let card = Color(white: 41.0 / 255)
    static let input = Color(white: 33.0 / 255)
    static let button = Color(white: 55.0 / 255)
    static let muted = Color(white: 0.64)
    static let accent = Color(red: 0.88, green: 0.26, blue: 0.32)
}
private struct Card<Content: View>: View {
    let title: String
    let subtitle: String?
    let fillHeight: Bool
    let content: Content
    init(_ title: String, subtitle: String? = nil, fillHeight: Bool = false, @ViewBuilder content: () -> Content) {
        self.title = title; self.subtitle = subtitle; self.fillHeight = fillHeight; self.content = content()
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 5) {
                Text(title).font(.system(size: 14, weight: .semibold))
                if let subtitle { Text(subtitle).font(.system(size: 12)).foregroundStyle(AppPalette.muted) }
            }
            content
        }
        .frame(maxWidth: .infinity, maxHeight: fillHeight ? .infinity : nil, alignment: .topLeading)
        .padding(20)
        .background(AppPalette.card, in: RoundedRectangle(cornerRadius: 14))
    }
}
private struct EqualHeightColumns: Layout {
    var spacing: CGFloat = 16
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? 700
        let column = max(0, (width - spacing * CGFloat(max(0, subviews.count - 1))) / CGFloat(max(1, subviews.count)))
        let height = subviews.map { $0.sizeThatFits(ProposedViewSize(width: column, height: nil)).height }.max() ?? 0
        return CGSize(width: width, height: height)
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let width = max(0, (bounds.width - spacing * CGFloat(max(0, subviews.count - 1))) / CGFloat(max(1, subviews.count)))
        for (index, view) in subviews.enumerated() {
            view.place(at: CGPoint(x: bounds.minX + CGFloat(index) * (width + spacing), y: bounds.minY),
                       anchor: .topLeading, proposal: ProposedViewSize(width: width, height: bounds.height))
        }
    }
}
private struct CardButtonStyle: ButtonStyle {
    var primary = false
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.system(size: 12, weight: .medium))
            .padding(.horizontal, 14).padding(.vertical, 9)
            .foregroundStyle(Color.white.opacity(enabled ? 0.94 : 0.32))
            .background((primary ? AppPalette.accent : AppPalette.button)
                .opacity(enabled ? (configuration.isPressed ? 0.7 : 1) : 0.5), in: RoundedRectangle(cornerRadius: 8))
            .contentShape(RoundedRectangle(cornerRadius: 8))
    }
}
private extension View {
    func cardField() -> some View {
        self.textFieldStyle(.plain).font(.system(size: 13))
            .padding(.horizontal, 12).padding(.vertical, 11)
            .background(AppPalette.input, in: RoundedRectangle(cornerRadius: 8))
    }
}
private struct Detail: View {
    let title: String
    let value: String
    init(_ title: String, _ value: Any?) { self.title = title; self.value = value.map { String(describing: $0) } ?? "—" }
    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title).font(.system(size: 11)).foregroundStyle(AppPalette.muted)
            Text(value).font(.system(size: 13, weight: .medium)).textSelection(.enabled)
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
}
private func phaseName(_ phase: String) -> String {
    ["armed": "已布防", "preparing": "准备中", "firing": "正在提交", "done": "已完成",
     "aborted": "已中止", "disarmed": "已取消"][phase] ?? phase
}
private func shortTime(_ value: Any?) -> String {
    guard let text = value as? String else { return "未记录" }
    return text.replacingOccurrences(of: "T", with: " ").components(separatedBy: ".")[0]
}

private struct WindowDragRegion: NSViewRepresentable {
    final class DragView: NSView {
        override var mouseDownCanMoveWindow: Bool { true }
        override func mouseDown(with event: NSEvent) { window?.performDrag(with: event) }
    }
    func makeNSView(context: Context) -> DragView { DragView() }
    func updateNSView(_ nsView: DragView, context: Context) {}
}
struct ManagementView: View {
    @EnvironmentObject var m: Model
    @State private var tab = 0
    private let pages = [("状态", "square.grid.2x2", "任务与设备"), ("系统", "desktopcomputer", "运行环境"), ("布防", "clock", "定时购买"), ("设置", "gearshape", "项目与凭据")]
    var body: some View {
        HStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 0) {
                WindowDragRegion().frame(height: 32)
                HStack(spacing: 10) {
                    Image(nsImage: NSApp.applicationIconImage).resizable().frame(width: 34, height: 34)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("招行理财值守").font(.system(size: 13, weight: .semibold))
                        Text("本机管理").font(.system(size: 11)).foregroundStyle(AppPalette.muted)
                    }
                }.padding(.top, 25).padding(.bottom, 32).background(WindowDragRegion())
                VStack(spacing: 7) {
                    ForEach(0..<3, id: \.self) { sidebarItem($0) }
                }
                Spacer(minLength: 28)
                sidebarItem(3)
                HStack(spacing: 7) {
                    Circle().fill(m.active ? AppPalette.accent : AppPalette.muted).frame(width: 5, height: 5)
                    Text(phaseName(m.phase)).font(.system(size: 11)).foregroundStyle(AppPalette.muted)
                }.padding(.horizontal, 12).padding(.top, 24).padding(.bottom, 8)
            }
            .padding(.horizontal, 16).padding(.top, 12).padding(.bottom, 16)
            .frame(width: 196).frame(maxHeight: .infinity)
            .background(Color(white: 35.0 / 255))
            VStack(alignment: .leading, spacing: 22) {
                HStack(alignment: .center) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(pages[tab].0).font(.system(size: 23, weight: .semibold))
                        Text(pages[tab].2).font(.system(size: 12)).foregroundStyle(AppPalette.muted)
                    }
                    Spacer()
                    if m.busy { ProgressView().controlSize(.small) }
                    Button { Task { await m.refresh() } } label: { Label("刷新", systemImage: "arrow.clockwise") }
                }.frame(height: 54).padding(.horizontal, 26).padding(.top, 20).background(WindowDragRegion())
                if let message = m.message {
                    HStack(alignment: .top) {
                        Image(systemName: "exclamationmark.circle").foregroundStyle(AppPalette.accent)
                        Text(message).font(.system(size: 12)).textSelection(.enabled)
                        Spacer()
                        Button("关闭") { m.message = nil }
                    }.padding(14).background(AppPalette.card, in: RoundedRectangle(cornerRadius: 10)).padding(.horizontal, 26)
                }
                ZStack {
                    StatusView().opacity(tab == 0 ? 1 : 0).allowsHitTesting(tab == 0).accessibilityHidden(tab != 0)
                    SystemView().opacity(tab == 1 ? 1 : 0).allowsHitTesting(tab == 1).accessibilityHidden(tab != 1)
                    ArmView().opacity(tab == 2 ? 1 : 0).allowsHitTesting(tab == 2).accessibilityHidden(tab != 2)
                    if tab == 3 { SettingsView() }
                }.disabled(m.root.isEmpty && tab != 3).frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(AppPalette.background)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity).ignoresSafeArea()
        .background(AppPalette.background)
        .foregroundStyle(Color(white: 0.94)).tint(AppPalette.accent)
        .buttonStyle(CardButtonStyle()).preferredColorScheme(.dark)
        .task {
            if m.root.isEmpty { tab = 3 }
            while !Task.isCancelled {
                await m.refresh()
                try? await Task.sleep(nanoseconds: 5_000_000_000)
            }
        }
        .onChange(of: tab) { value in
            Task {
                if value == 0 { await m.action(["device"]) }
                if value == 1 { await m.action(["system"]); await m.action(["device"]) }
                if value == 2 { await m.action(["history"]) }
            }
        }
    }
    private func sidebarItem(_ index: Int) -> some View {
        Button { tab = index } label: {
            HStack(spacing: 11) {
                Image(systemName: pages[index].1).font(.system(size: 14)).frame(width: 20)
                Text(pages[index].0).font(.system(size: 13, weight: tab == index ? .semibold : .regular))
                Spacer()
            }
            .foregroundStyle(tab == index ? Color.white : AppPalette.muted)
            .padding(.horizontal, 12).padding(.vertical, 12)
            .background(tab == index ? AppPalette.button : Color.clear, in: RoundedRectangle(cornerRadius: 9))
            .contentShape(RoundedRectangle(cornerRadius: 9))
        }.buttonStyle(.plain)
    }
}
private struct ProjectSettingsCard: View {
    @EnvironmentObject var m: Model
    var body: some View {
        Card("项目设置", subtitle: "选择本机项目目录和 Python 解释器") {
            VStack(alignment: .leading, spacing: 8) {
                Text("项目目录").font(.caption).foregroundStyle(AppPalette.muted)
                HStack(spacing: 10) {
                    TextField("选择项目目录", text: $m.root).cardField().onSubmit { m.saveSettings() }
                    Button("选择…", action: m.chooseProject)
                }
            }
            VStack(alignment: .leading, spacing: 8) {
                Text("Python 路径").font(.caption).foregroundStyle(AppPalette.muted)
                TextField("Python 绝对路径", text: $m.python).cardField().onSubmit { m.saveSettings() }
            }
            HStack { Spacer(); Button("保存设置", action: m.saveSettings).buttonStyle(CardButtonStyle(primary: true)) }
        }
    }
}
struct StatusView: View {
    @EnvironmentObject var m: Model
    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                Card("当前任务") {
                    if m.task.isEmpty {
                        Text("尚未布防").font(.system(size: 22, weight: .medium))
                        Text("前往布防页设置产品、金额与开售时间。").font(.system(size: 12)).foregroundStyle(AppPalette.muted)
                    } else {
                        HStack(alignment: .firstTextBaseline) {
                            Text(String(describing: m.task["code"] ?? "—")).font(.system(size: 24, weight: .semibold, design: .rounded))
                            Spacer()
                            Text("¥ " + String(describing: m.task["amount"] ?? "—")).font(.system(size: 22, weight: .medium, design: .rounded)).monospacedDigit()
                        }
                        Text("开售时间  " + shortTime(m.task["at"])).font(.system(size: 12)).foregroundStyle(AppPalette.muted)
                        HStack(alignment: .top, spacing: 16) {
                            Detail("值守进程", m.status["running"] as? Bool == true ? "运行中" : "未运行")
                            Detail("任务类型", m.task["dry_run"] as? Bool == true ? "演练" : "真实任务")
                            Detail("图案输入", "\(m.task["patterns_sent"] ?? 0) 次")
                            Detail("最近心跳", shortTime(m.task["last_tick"]))
                        }
                    }
                    if m.status["stale"] as? Bool == true { Text("值守可能卡住").font(.caption).foregroundStyle(.orange) }
                    if m.status["legacy"] as? Bool == true { Text("旧版本任务，不能恢复").font(.caption).foregroundStyle(.orange) }
                    if m.phase == "firing" && m.status["running"] as? Bool != true {
                        Text("提交中进程已退出：先查交易记录，不要补单或重试。确认后由账户持有人按操作手册处理任务文件。").font(.caption).foregroundStyle(.red)
                    }
                    Divider().overlay(Color.white.opacity(0.04))
                    HStack { Label(m.agent, systemImage: "antenna.radiowaves.left.and.right").font(.system(size: 12)).foregroundStyle(AppPalette.muted); Spacer(); Button("复制监听指令", action: m.copyWatch) }
                }
                Card("模拟器") {
                    HStack(spacing: 16) {
                        Detail("运行状态", (m.device["emulator"] as? [String: Any])?["running"] as? Bool == true ? "运行中" : "未运行 / 未刷新")
                        Detail("开机状态", m.device["booted"] as? Bool == true ? "已完成" : "未完成 / 未刷新")
                        Detail("分辨率", m.device["resolution"])
                        Detail("App 进程", m.device["app_pid"])
                    }
                    HStack {
                        Button("刷新设备") { Task { await m.action(["device"]) } }
                        Button("启动模拟器") { Task { await m.action(["emulator", "start"]) } }
                        Button("关闭模拟器") { Task { await m.action(["emulator", "stop"]) } }.disabled(m.active)
                        Spacer()
                        Button { Task { await m.action(["screenshot"]) } } label: { Label("截图", systemImage: "camera") }
                    }.disabled(m.busy)
                    if let image = m.screenshot { Image(nsImage: image).resizable().scaledToFit().frame(maxHeight: 350).frame(maxWidth: .infinity) }
                }
                Card("最近日志") {
                    if (m.status["logs"] as? [String] ?? []).isEmpty {
                        Text("暂无日志").font(.system(size: 12)).foregroundStyle(AppPalette.muted)
                    } else {
                        ScrollView([.vertical, .horizontal]) {
                            Text((m.status["logs"] as? [String] ?? []).joined(separator: "\n"))
                                .font(.system(size: 11, design: .monospaced)).lineSpacing(5)
                                .foregroundStyle(Color(white: 0.72)).textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }.frame(height: 200)
                    }
                }
            }.padding(.horizontal, 26).padding(.bottom, 26)
        }
    }
}
struct SystemView: View {
    @EnvironmentObject var m: Model
    private var networkTime: String {
        guard let value = m.system["network_s"] as? NSNumber else { return "未连接" }
        return String(format: "%.3f 秒", value.doubleValue)
    }
    private var lidState: String {
        let value = m.system["clamshell"] as? String ?? ""
        if value.contains("No") { return "已打开" }
        if value.contains("Yes") { return "已合盖" }
        return "无法读取"
    }
    func row(_ title: String, _ good: Bool?, _ advice: String) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: good == nil ? "minus.circle" : good == true ? "checkmark.circle" : "exclamationmark.circle")
                .foregroundStyle(good == nil ? AppPalette.muted : good == true ? Color.green : Color.orange)
                .frame(width: 16)
            Text(title).font(.system(size: 13, weight: .medium)).frame(width: 105, alignment: .leading)
            Text(advice).font(.system(size: 12)).foregroundStyle(AppPalette.muted).frame(maxWidth: .infinity, alignment: .leading)
        }
    }
    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                HStack { Text("电源、网络与设备检查").font(.system(size: 12)).foregroundStyle(AppPalette.muted); Spacer(); Button("刷新系统与设备") { Task { await m.action(["system"]); await m.action(["device"]) } }.disabled(m.busy) }
                Card("Mac") {
                    row("电源", m.system["on_ac"] as? Bool, m.system.isEmpty ? "尚未检查" : m.system["on_ac"] as? Bool == true ? "已接通电源" : "正在使用电池；请接电源，合盖会休眠。")
                    row("值守防休眠", m.system.isEmpty ? nil : m.system["watch_caffeinate"] as? Bool == true || !m.active, "值守运行时应有专属 caffeinate 防休眠声明。")
                    row("网络", m.system["network_ok"] as? Bool, "连接耗时 \(networkTime)；异常时检查网络。")
                    Detail("合盖状态", lidState)
                    Detail("锁屏", m.system["lock"] ?? "无法读取；锁屏本身不影响值守")
                    DisclosureGroup("查看休眠设置") {
                        Text(String(describing: m.system["sleep_settings"] ?? "未刷新"))
                            .font(.system(size: 11, design: .monospaced)).foregroundStyle(AppPalette.muted)
                            .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading).padding(.top, 10)
                    }.font(.system(size: 12)).foregroundStyle(AppPalette.muted)
                }
                Card("模拟器") {
                    row("屏幕", m.device.isEmpty ? nil : m.device["awake"] as? Bool == true, "期望 Awake")
                    row("插电常亮", m.device.isEmpty ? nil : m.device["stay_on"] as? String == "15", "当前：\(m.device["stay_on"] ?? "—")，期望 15")
                    row("模拟 AC", m.device.isEmpty ? nil : m.device["ac_powered"] as? Bool == true, "期望接通")
                    row("熄屏时间", m.device.isEmpty ? nil : m.device["screen_timeout"] as? String == "2147483647", "当前：\(m.device["screen_timeout"] ?? "—")")
                    row("锁屏禁用", m.device.isEmpty ? nil : m.device["lock_disabled"] as? String == "true", "当前：\(m.device["lock_disabled"] ?? "—")")
                    Button("恢复模拟器常亮") { Task { await m.action(["keep-awake"]); await m.action(["device"]) } }.disabled(m.busy)
                }
            }.padding(.horizontal, 26).padding(.bottom, 26)
        }
    }
}
struct ArmView: View {
    @EnvironmentObject var m: Model
    @State private var code = ""
    @State private var amount = ""
    @State private var confirmAmount = ""
    @State private var date = Calendar.current.date(bySettingHour: 9, minute: 0, second: 0, of: Calendar.current.date(byAdding: .day, value: 1, to: Date())!)!
    @State private var prep = 15
    @State private var dry = true
    @State private var now = false
    @State private var confirmation = false
    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                Card("首发模式", subtitle: "捡漏模式、赎回抢购模式规划中") {
                    HStack(alignment: .top, spacing: 16) {
                        VStack(alignment: .leading, spacing: 8) { Text("产品代码").font(.caption).foregroundStyle(AppPalette.muted); TextField("输入产品代码", text: $code).cardField() }
                        VStack(alignment: .leading, spacing: 8) { Text("购买金额").font(.caption).foregroundStyle(AppPalette.muted); TextField("上限 50000 元，最多两位小数", text: $amount).cardField() }
                    }
                    DatePicker("开售时间", selection: $date, displayedComponents: [.date, .hourAndMinute]).disabled(now)
                    HStack { Stepper("提前 \(prep) 分钟准备", value: $prep, in: 5...15); Spacer(); Text("200ms 由脚本自动加").font(.caption).foregroundStyle(AppPalette.muted) }
                }
                Card("执行方式") {
                    Toggle("演练：只到密码页，不输入密码、不提交", isOn: $dry).onChange(of: dry) { if !$0 { now = false } }
                    Toggle("立即排练", isOn: $now).disabled(!dry)
                    HStack {
                        Button(dry ? "开始演练布防" : "布防") { confirmAmount = ""; confirmation = true }.buttonStyle(CardButtonStyle(primary: true)).disabled(m.busy || m.active)
                        Button("取消布防") { Task { await m.action(["disarm"]) } }.disabled(m.busy || m.phase == "firing" || !m.active)
                        Spacer()
                        Text("以银行交易记录为准").font(.caption).foregroundStyle(AppPalette.muted)
                    }
                    if m.phase == "firing" { Text("正在提交，等结果并查交易记录").font(.caption).foregroundStyle(.red) }
                }
                Card("最近值守") {
                    HStack { Text("最近 20 条记录").font(.caption).foregroundStyle(AppPalette.muted); Spacer(); Button("刷新历史") { Task { await m.action(["history"]) } } }
                    if m.history.isEmpty { Text("暂无历史记录").font(.system(size: 12)).foregroundStyle(AppPalette.muted) }
                    ForEach(Array(m.history.enumerated()), id: \.offset) { _, item in
                        HStack(alignment: .top) {
                            VStack(alignment: .leading, spacing: 6) { Text(verbatim: "\(item["code"] ?? "") · \(item["amount"] ?? "") 元").font(.system(size: 13, weight: .medium)); Text(shortTime(item["at"])).font(.caption).foregroundStyle(AppPalette.muted) }
                            Spacer()
                            VStack(alignment: .trailing, spacing: 6) { Text(phaseName(item["phase"] as? String ?? "")).font(.system(size: 12)); Text(String(describing: item["result"] ?? "")).font(.caption).foregroundStyle(AppPalette.muted) }
                        }.textSelection(.enabled)
                    }
                }
            }.padding(.horizontal, 26).padding(.bottom, 26)
        }
        .toggleStyle(.switch)
        .sheet(isPresented: $confirmation) {
            VStack(alignment: .leading, spacing: 20) {
                Text(dry ? "确认演练" : "确认真实布防").font(.system(size: 20, weight: .semibold))
                Text("产品 \(code)，将在 \(now ? "三分钟后" : date.formatted()) \(dry ? "演练" : "真实提交一次") \(amount) 元。").font(.system(size: 13))
                if !dry { TextField("再输入一次金额", text: $confirmAmount).cardField() }
                HStack {
                    Spacer()
                    Button("取消") { confirmation = false }
                    Button("确定") {
                        confirmation = false
                        let formatter = DateFormatter(); formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
                        var args = ["arm", "--code", code, "--amount", amount, "--prep-minutes", String(prep)]
                        args += now ? ["--now"] : ["--at", formatter.string(from: date)]
                        if dry { args.append("--dry-run") }
                        Task { await m.action(args) }
                    }.buttonStyle(CardButtonStyle(primary: true)).disabled(!dry && (confirmAmount != amount || amount.isEmpty))
                }
            }.padding(28).frame(width: 440).background(AppPalette.background)
                .buttonStyle(CardButtonStyle()).preferredColorScheme(.dark)
        }
    }
}
struct SettingsView: View {
    @EnvironmentObject var m: Model
    @State private var pattern = ""
    @State private var repeated = ""
    @State private var current = ""
    @State private var password = ""
    @State private var again = ""
    @State private var second = false
    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                ProjectSettingsCard()
                Card("凭据状态", subtitle: "这里只同步脚本保存的值，不会修改银行 App 中的设置。") {
                    HStack { Detail("登录与交易凭据", m.credentialState); Detail("邮件通知", m.status["mail_configured"] as? Bool == true ? "已配置" : "未配置") }
                }
                EqualHeightColumns {
                    Card("九宫格图案", subtitle: "先在银行 App 修改，再到这里同步", fillHeight: true) {
                        VStack(spacing: 18) {
                            Text(second ? "再次点选相同图案" : "点选 4–9 个不重复的点").font(.system(size: 12)).foregroundStyle(AppPalette.muted)
                            ForEach(0..<3) { row in
                                HStack(spacing: 24) {
                                    ForEach(1..<4) { col in
                                        let point = String(row * 3 + col)
                                        Button { if second { if !repeated.contains(point) { repeated += point } } else { if !pattern.contains(point) { pattern += point } } } label: {
                                            Circle().fill((second ? repeated : pattern).contains(point) ? AppPalette.accent : Color(white: 0.38)).frame(width: 27, height: 27).frame(width: 36, height: 36)
                                        }.buttonStyle(.plain)
                                    }
                                }
                            }
                            Text("已选 \((second ? repeated : pattern).count) 个点").font(.caption).foregroundStyle(AppPalette.muted)
                            HStack {
                                Button("重画") { pattern = ""; repeated = ""; second = false }
                                if !second { Button("再画一次") { second = true }.disabled(pattern.count < 4) }
                                else {
                                    Button("保存图案") {
                                        let value = pattern
                                        pattern = ""; repeated = ""; second = false
                                        Task { await m.action(["set-login-pattern"], input: ["new": value]) }
                                    }.disabled(pattern != repeated || pattern.count < 4)
                                }
                            }
                        }.frame(maxWidth: .infinity).padding(.vertical, 8)
                    }
                    Card("交易密码", subtitle: "请输入当前密码以验证修改", fillHeight: true) {
                        SecureField("当前密码", text: $current).cardField()
                        SecureField("新密码", text: $password).cardField()
                        SecureField("再次输入新密码", text: $again).cardField()
                        Text("6 位数字，保存后立即清空输入。").font(.caption).foregroundStyle(AppPalette.muted)
                        Button("保存交易密码") {
                            let input = ["current": current, "new": password]
                            current = ""; password = ""; again = ""
                            Task { await m.action(["set-payment-password"], input: input) }
                        }.buttonStyle(CardButtonStyle(primary: true)).disabled(password != again || !valid(password) || !valid(current))
                    }
                }
            }.padding(.horizontal, 26).padding(.bottom, 26)
        }.disabled(m.credentialsDisabled || m.busy)
        .onDisappear { pattern = ""; repeated = ""; current = ""; password = ""; again = ""; second = false }
    }
    func valid(_ value: String) -> Bool { value.count == 6 && value.utf8.allSatisfy { (48...57).contains($0) } }
}
