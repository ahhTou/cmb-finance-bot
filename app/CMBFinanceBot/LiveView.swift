import SwiftUI

/// Full-window focus view while a watch task is active.
///
/// Shows only the current task and a live log stream; the log runs as a
/// low-contrast background layer, the countdown and task facts sit on a
/// single compact panel. The single action is terminating the task.
struct LiveView: View {
    @EnvironmentObject var m: Model
    @State private var now = Date()
    @State private var confirmDisarm = false

    private var redemption: Bool { (m.task["mode"] as? String) == "redemption" }
    private var code: String { stringValue(m.task["code"]) ?? "—" }
    private var amount: String { stringValue(m.task["amount"]) ?? "—" }
    private var prep: String { stringValue(m.task["prep_minutes"]) ?? "—" }
    private var window: String { stringValue(m.task["window_minutes"]) ?? "—" }
    private var fireAt: Date? { parseISO(m.task["fire_at"]) ?? parseISO(m.task["at"]) }
    private var endAt: Date? { parseISO(m.task["end_at"]) }

    var body: some View {
        ZStack {
            AppPalette.background.ignoresSafeArea()
            logBackground
            VStack(spacing: 0) {
                topBar
                Spacer(minLength: 24)
                panel
            }
            .padding(.horizontal, 30)
            .padding(.vertical, 26)
        }
        .task {
            while !Task.isCancelled {
                now = Date()
                await m.loadLog()
                try? await Task.sleep(nanoseconds: 1_500_000_000)
            }
        }
        .alert("终止本轮布防？", isPresented: $confirmDisarm) {
            Button("继续值守", role: .cancel) {}
            Button("确认终止", role: .destructive) {
                Task { await m.action(["disarm"], label: "终止布防") }
            }
        } message: {
            Text("终止后不会再提交；已经发生的交易仍要查交易记录。")
        }
    }

    // MARK: 背景日志

    private var logBackground: some View {
        ScrollViewReader { proxy in
            ScrollView(showsIndicators: false) {
                LazyVStack(alignment: .leading, spacing: 3) {
                    ForEach(Array(m.logLines.suffix(300).enumerated()), id: \.offset) { _, line in
                        Text(line)
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundStyle(Color(white: 0.58))
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                    Color.clear.frame(height: 1).id("tail")
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 30)
                .padding(.top, 74)
                .padding(.bottom, 250)
            }
            .onAppear { proxy.scrollTo("tail", anchor: .bottom) }
            .onChange(of: m.logLines.last) { _ in
                proxy.scrollTo("tail", anchor: .bottom)
            }
        }
        .allowsHitTesting(false)
        .opacity(0.55)
    }

    // MARK: 顶部状态

    private var topBar: some View {
        HStack(spacing: 12) {
            Circle().fill(phaseColor(m.phase)).frame(width: 7, height: 7)
            Text(phaseName(m.phase)).font(.system(size: 13, weight: .semibold))
            Text(redemption ? "不定时抢购" : "首发模式")
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(AppPalette.muted)
                .padding(.horizontal, 8).padding(.vertical, 3)
                .background(Color(white: 0.22), in: Capsule())
            Spacer()
            Text("上次刷新 \(m.lastRefreshText)")
                .font(.system(size: 10, design: .monospaced))
                .foregroundStyle(AppPalette.muted)
        }
    }

    // MARK: 任务面板

    private var panel: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .lastTextBaseline, spacing: 14) {
                Text(countdownText)
                    .font(.system(size: 58, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                Text(countdownHint)
                    .font(.system(size: 12))
                    .foregroundStyle(AppPalette.muted)
                    .padding(.bottom, 11)
                Spacer()
            }
            Rectangle().fill(Color(white: 0.28)).frame(height: 0.6)
            HStack(alignment: .bottom, spacing: 36) {
                stat("产品", code)
                stat("金额", "\(amount) 元")
                stat("计划", shortTime(m.task["at"]))
                if redemption {
                    stat("窗口", "\(window) 分钟")
                } else {
                    stat("提前量", "\(prep) 分钟")
                }
                Spacer()
                Button("终止布防") { confirmDisarm = true }
                    .buttonStyle(CardButtonStyle(primary: true))
                    .disabled(m.busy || m.phase == "firing")
            }
        }
        .padding(26)
        .background(Color(white: 0.13).opacity(0.97), in: RoundedRectangle(cornerRadius: 18))
        .overlay(RoundedRectangle(cornerRadius: 18).stroke(Color(white: 0.3), lineWidth: 0.6))
    }

    private func stat(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title).font(.system(size: 10)).foregroundStyle(AppPalette.muted)
            Text(value)
                .font(.system(size: 18, weight: .medium, design: .rounded))
                .monospacedDigit()
        }
    }

    private var targetDate: Date? {
        if redemption, m.phase == "waiting" || m.phase == "firing" { return endAt }
        return fireAt
    }

    private var countdownText: String {
        if m.phase == "firing" { return "00:00" }
        guard let target = targetDate else { return "--:--" }
        let diff = target.timeIntervalSince(now)
        if diff <= 0 { return "00:00" }
        let total = Int(diff)
        let hours = total / 3600
        let minutes = (total % 3600) / 60
        let seconds = total % 60
        return hours > 0
            ? String(format: "%d:%02d:%02d", hours, minutes, seconds)
            : String(format: "%02d:%02d", minutes, seconds)
    }

    private var countdownHint: String {
        if m.phase == "firing" { return "正在提交，请勿操作" }
        if redemption {
            return m.phase == "waiting" ? "距窗口结束" : "距开始查询"
        }
        return "距开售"
    }
}

private func parseISO(_ value: Any?) -> Date? {
    guard var text = stringValue(value) else { return nil }
    if text.count >= 19 { text = String(text.prefix(19)) }
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.timeZone = .current
    formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
    if let date = formatter.date(from: text) { return date }
    formatter.dateFormat = "HH:mm:ss"
    guard let time = formatter.date(from: text) else { return nil }
    let parts = Calendar.current.dateComponents([.hour, .minute, .second], from: time)
    return Calendar.current.date(bySettingHour: parts.hour ?? 0, minute: parts.minute ?? 0,
                                 second: parts.second ?? 0, of: Date())
}
