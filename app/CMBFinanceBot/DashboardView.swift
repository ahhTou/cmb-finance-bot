import SwiftUI
import AppKit

struct DashboardView: View {
    @EnvironmentObject var m: Model
    @Binding var tab: Int
    @State private var showSleep = false
    @State private var showLog = false
    @State private var showScreenshot = false
    @State private var showEmulator = false

    var body: some View {
        GeometryReader { geo in
            let spacing: CGFloat = 16
            let row = max(180, (geo.size.height - spacing * 2) / 3)
            ScrollView {
                VStack(spacing: spacing) {
                    HStack(spacing: 16) {
                        watchCard.frame(height: row)
                        macCard.frame(height: row)
                    }
                    HStack(spacing: 16) {
                        emulatorCard.frame(height: row)
                        screenshotCard.frame(height: row)
                    }
                    HStack(spacing: 16) {
                        configCard.frame(height: row)
                        logCard.frame(height: row)
                    }
                }
                .padding(.horizontal, 26)
                .frame(maxWidth: .infinity, alignment: .top)
            }
        }
        .sheet(isPresented: $showSleep) { sleepSheet }
        .sheet(isPresented: $showLog) { logSheet }
        .sheet(isPresented: $showScreenshot) { screenshotSheet }
        .sheet(isPresented: $showEmulator) { emulatorSheet }
    }

    private var watchCard: some View {
        DashboardCard("值守", icon: "shield.lefthalf.filled") {
            if m.task.isEmpty {
                HStack(spacing: 8) { StatusDot(state: nil); Text("未布防").font(.system(size: 12, weight: .medium)) }
                Text("去任务页选择首发或不定时抢购模式布防。").font(.system(size: 11)).foregroundStyle(AppPalette.muted)
            } else {
                HStack(spacing: 8) {
                    Badge(text: phaseName(m.phase), color: phaseColor(m.phase))
                    if boolValue(m.task["dry_run"]) == true { Badge(text: "演练") }
                    Spacer()
                    Text(m.running ? "运行中" : "未运行")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(m.running ? AppPalette.good : AppPalette.warn)
                }
                MetricGrid {
                    Metric("最近心跳", ageText(m.status["last_tick_age_s"]))
                    Metric("Agent", m.agentShort)
                    Metric("日志", "\((m.status["logs"] as? [String] ?? []).count) 行")
                    Metric("值守进程", m.running ? "运行中" : "未运行", color: m.running ? AppPalette.good : AppPalette.warn)
                }
                if m.phase == "firing" && !m.running {
                    Text("提交中进程已退出：先查交易记录，不要补单或重试。")
                        .font(.system(size: 10)).foregroundStyle(AppPalette.accent)
                }
            }
        } footer: {
            if m.task.isEmpty {
                HStack { Button("去任务页") { tab = 0 }; Spacer() }
            } else {
                HStack(spacing: 8) {
                    Button("刷新") { Task { await m.refresh() } }.disabled(m.busy)
                    Button("复制监听指令", action: m.copyWatch)
                    Spacer()
                    if m.active { Button("去任务页") { tab = 0 } }
                }
            }
        }
    }

    private var macCard: some View {
        DashboardCard("Mac", icon: "laptopcomputer") {
            MetricGrid {
                Metric("电源", powerText, color: onAC == nil ? nil : (onAC! ? AppPalette.good : AppPalette.warn))
                Metric("合盖", lidText)
                Metric("防休眠", caffeinateText, color: caffeinate == nil ? nil : (caffeinate! ? AppPalette.good : AppPalette.warn))
                Metric("网络", networkText, color: networkOK == nil ? nil : (networkOK! ? AppPalette.good : AppPalette.warn))
            }
        } footer: {
            HStack(spacing: 8) {
                Button("刷新") { Task { await m.loadDashboard() } }.disabled(m.busy)
                Button("休眠设置") { showSleep = true }
                Spacer()
                Text("只读").font(.system(size: 9)).foregroundStyle(AppPalette.muted)
            }
        }
    }

    private var emulatorCard: some View {
        DashboardCard("模拟器", icon: "iphone") {
            MetricGrid {
                Metric("运行", m.device.isEmpty ? "尚未刷新" : (emulatorRunning ? "运行中" : "未运行"),
                       color: m.device.isEmpty ? nil : (emulatorRunning ? AppPalette.good : AppPalette.warn))
                Metric("开机", m.device.isEmpty ? "尚未刷新" : (emulatorRunning ? (booted ? "已完成" : "未完成") : "未运行"))
                Metric("App 进程", emulatorRunning ? appPid : "—")
                Metric("屏幕", !emulatorRunning || awake == nil ? "—" : (awake! ? "Awake" : "休眠"))
                Metric("插电常亮", emulatorRunning ? (stayOn == "15" ? "已开启" : "未开启") : "—")
                Metric("锁屏禁用", emulatorRunning ? (lockDisabled == "true" ? "已禁用" : "未禁用") : "—")
            }
        } footer: {
            HStack(spacing: 6) {
                Button("启动") { Task { await m.action(["emulator", "start"], label: "启动模拟器") } }
                    .buttonStyle(CompactButtonStyle()).disabled(m.busy || m.active)
                Button("关闭") { Task { await m.action(["emulator", "stop"], label: "关闭模拟器") } }
                    .buttonStyle(CompactButtonStyle()).disabled(m.busy || m.active)
                Button("恢复常亮") { Task { await m.action(["keep-awake"], label: "恢复常亮") } }
                    .buttonStyle(CompactButtonStyle()).disabled(m.busy)
                Button("截图") { Task { await m.action(["screenshot"], label: "截取画面") } }
                    .buttonStyle(CompactButtonStyle()).disabled(m.busy)
                Spacer(minLength: 4)
                Button("详情") { showEmulator = true }.buttonStyle(CompactButtonStyle())
            }
        }
    }

    private var screenshotCard: some View {
        DashboardCard("画面", icon: "camera") {
            if let image = m.screenshot {
                Image(nsImage: image).resizable().interpolation(.medium).scaledToFit()
                    .frame(maxWidth: .infinity, maxHeight: 90)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .onTapGesture { showScreenshot = true }
                    .pointingHand()
            } else {
                VStack(spacing: 6) {
                    Image(systemName: "photo").font(.system(size: 22)).foregroundStyle(AppPalette.muted)
                    Text("还没有截图").font(.system(size: 11)).foregroundStyle(AppPalette.muted)
                }
                .frame(maxWidth: .infinity, maxHeight: 80)
            }
        } footer: {
            HStack(spacing: 8) {
                Button("截图") { Task { await m.action(["screenshot"], label: "截取画面") } }.disabled(m.busy)
                if m.screenshot != nil { Button("放大") { showScreenshot = true } }
                Spacer()
                Text("仅本机").font(.system(size: 9)).foregroundStyle(AppPalette.muted)
            }
        }
    }

    private var configCard: some View {
        DashboardCard("凭据与通知", icon: "key") {
            MetricGrid {
                Metric("登录与交易凭据", m.credentialState,
                       color: m.credentialState == "已设置" ? AppPalette.good : AppPalette.warn)
                Metric("邮件通知", m.mailConfigured ? "已配置" : "未配置",
                       color: m.mailConfigured ? AppPalette.good : nil)
            }
        } footer: {
            HStack(spacing: 8) {
                Button("打开设置") { tab = 5 }
                Spacer()
                Text("不修改银行设置").font(.system(size: 9)).foregroundStyle(AppPalette.muted)
            }
        }
    }

    private var logCard: some View {
        let lines = Array((m.status["logs"] as? [String] ?? []).suffix(6))
        return DashboardCard("最近日志", icon: "doc.text") {
            if lines.isEmpty {
                Text("暂无日志").font(.system(size: 11)).foregroundStyle(AppPalette.muted)
            } else {
                Text(lines.joined(separator: "\n"))
                    .font(.system(size: 9, design: .monospaced))
                    .lineSpacing(2)
                    .foregroundStyle(Color(white: 0.72))
                    .lineLimit(6)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        } footer: {
            HStack(spacing: 8) {
                Button("查看日志") {
                    Task {
                        await m.loadLog()
                        showLog = true
                    }
                }.disabled(m.busy)
                Spacer()
                Text("最近 6 行").font(.system(size: 9)).foregroundStyle(AppPalette.muted)
            }
        }
    }

    private var sleepSheet: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("休眠设置").font(.system(size: 17, weight: .semibold))
                Spacer()
                Button("关闭") { showSleep = false }
            }
            LogText(lines: stringValue(m.system["sleep_settings"])?.components(separatedBy: "\n") ?? ["未刷新"])
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            Text("只读展示 pmset 输出，不修改 Mac 设置。").font(.system(size: 10)).foregroundStyle(AppPalette.muted)
        }
        .padding(24).frame(width: 760, height: 460)
        .background(AppPalette.background).buttonStyle(CardButtonStyle()).preferredColorScheme(.dark)
    }

    private var logSheet: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("值守日志").font(.system(size: 17, weight: .semibold))
                Spacer()
                Button("复制") { copyText(m.logLines.joined(separator: "\n")) }
                Button("打开文件") {
                    guard !m.logPath.isEmpty else { return }
                    NSWorkspace.shared.open(URL(fileURLWithPath: m.logPath))
                }.disabled(m.logPath.isEmpty)
                Button("关闭") { showLog = false }
            }
            LogText(lines: m.logLines).frame(maxWidth: .infinity, maxHeight: .infinity)
            Text("日志为全局 watch.log，不按任务拆分。").font(.system(size: 10)).foregroundStyle(AppPalette.muted)
        }
        .padding(24).frame(width: 860, height: 580)
        .background(AppPalette.background).buttonStyle(CardButtonStyle()).preferredColorScheme(.dark)
    }

    private var screenshotSheet: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("模拟器画面").font(.system(size: 17, weight: .semibold))
                Spacer()
                Button("关闭") { showScreenshot = false }
            }
            if let image = m.screenshot {
                Image(nsImage: image).resizable().interpolation(.medium).scaledToFit()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                Text("还没有截图").foregroundStyle(AppPalette.muted).frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .padding(24).frame(width: 760, height: 620)
        .background(AppPalette.background).buttonStyle(CardButtonStyle()).preferredColorScheme(.dark)
    }

    private var emulatorSheet: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("模拟器详情").font(.system(size: 17, weight: .semibold))
                Spacer()
                Button("关闭") { showEmulator = false }
            }
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 16) {
                Detail("运行状态", emulatorRunning ? "运行中" : "未运行")
                Detail("开机状态", booted ? "已完成" : "未完成")
                Detail("分辨率", resolution)
                Detail("App 进程", appPid)
                Detail("屏幕", awake == nil ? "无法读取" : (awake! ? "Awake" : "休眠"))
                Detail("分辨率正确", boolValue(m.device["resolution_ok"]) == true ? "是" : "否 / 无法读取")
                Detail("插电常亮", stayOn)
                Detail("模拟 AC", acPowered == nil ? "无法读取" : (acPowered! ? "已接通" : "未接通"))
                Detail("熄屏时间", screenTimeout)
                Detail("锁屏禁用", lockDisabled)
            }
            Text("屏幕、常亮与模拟 AC 在模拟器重启后可能丢失，可回到 Dashboard 恢复常亮。")
                .font(.system(size: 10)).foregroundStyle(AppPalette.muted)
        }
        .padding(24).frame(width: 680, height: 430)
        .background(AppPalette.background).buttonStyle(CardButtonStyle()).preferredColorScheme(.dark)
    }

    private var emulator: [String: Any] { dictValue(m.device["emulator"]) }
    private var emulatorRunning: Bool { boolValue(emulator["running"]) == true }
    private var booted: Bool { boolValue(m.device["booted"]) == true }
    private var awake: Bool? { boolValue(m.device["awake"]) }
    private var stayOn: String { stringValue(m.device["stay_on"]) ?? "—" }
    private var lockDisabled: String { stringValue(m.device["lock_disabled"]) ?? "—" }
    private var appPid: String {
        let value = stringValue(m.device["app_pid"]) ?? "—"
        return value == "-1" || value.isEmpty ? "未运行" : value
    }
    private var resolution: String { stringValue(m.device["resolution"]) ?? "—" }
    private var acPowered: Bool? { boolValue(m.device["ac_powered"]) }
    private var screenTimeout: String { stringValue(m.device["screen_timeout"]) ?? "—" }
    private var onAC: Bool? { boolValue(m.system["on_ac"]) }
    private var caffeinate: Bool? { boolValue(m.system["watch_caffeinate"]) }
    private var networkOK: Bool? { boolValue(m.system["network_ok"]) }
    private var lidText: String {
        guard let value = stringValue(m.system["clamshell"]) else { return "—" }
        if value.contains("No") { return "已打开" }
        if value.contains("Yes") { return "已合盖" }
        return "无法读取"
    }
    private var powerText: String {
        guard let onAC else { return "尚未刷新" }
        return onAC ? "已接电源" : "电池供电"
    }
    private var caffeinateText: String {
        guard let caffeinate else { return "尚未刷新" }
        return caffeinate ? "已声明" : "未声明"
    }
    private var networkText: String {
        if let value = m.system["network_s"] as? NSNumber {
            return String(format: "%.3f 秒", value.doubleValue)
        }
        return m.system.isEmpty ? "尚未检查" : "异常"
    }
}
