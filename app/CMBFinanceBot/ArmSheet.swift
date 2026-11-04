import SwiftUI

enum ArmMode: String {
    case firstLaunch = "first_launch"
    case redemption = "redemption"

    var title: String { self == .redemption ? "不定时抢购" : "首发" }
    var blurb: String {
        self == .redemption
            ? "不定时抢购模式 · 有额度才提交，一笔只提交一次"
            : "首发模式 · 一笔只提交一次"
    }
}

private let quotaTimes = ["00:15", "09:00", "09:15", "10:15", "11:15"]

private func nextQuotaDate(_ time: String, after earliest: Date = Date().addingTimeInterval(9 * 60)) -> Date {
    let parts = time.split(separator: ":").compactMap { Int($0) }
    return Calendar.current.nextDate(after: earliest,
        matching: DateComponents(hour: parts[0], minute: parts[1], second: 0),
        matchingPolicy: .nextTime) ?? earliest
}

private func armDefaultDate(_ mode: ArmMode) -> Date {
    if mode == .redemption {
        return quotaTimes.map { nextQuotaDate($0) }.min() ?? Date()
    }
    let tomorrow = Calendar.current.date(byAdding: .day, value: 1, to: Date()) ?? Date()
    return Calendar.current.date(bySettingHour: 9, minute: 0, second: 0, of: tomorrow) ?? tomorrow
}

struct ArmSheet: View {
    @EnvironmentObject var m: Model
    @Environment(\.dismiss) private var dismiss
    let drillOnly: Bool
    let mode: ArmMode

    @State private var code = ""
    @State private var amount = ""
    @State private var date: Date
    @State private var timeChoice: String
    @State private var settings: [String: Int] = [:]
    @State private var settingsLoaded = false
    @State private var settingsRevision = ""
    @State private var dry = false
    @State private var now = false
    @State private var confirm = false
    @State private var confirmAmount = ""
    @State private var step: String?
    @State private var working = false

    init(drill: Bool = false, mode: ArmMode = .firstLaunch) {
        self.drillOnly = drill
        self.mode = mode
        let initialDate = armDefaultDate(mode)
        _date = State(initialValue: initialDate)
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        _timeChoice = State(initialValue: formatter.string(from: initialDate))
        _dry = State(initialValue: drill)
        _now = State(initialValue: drill)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack(alignment: .center) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(confirm ? "确认布防"
                         : (drillOnly ? "演练布防" : "新建\(mode == .redemption ? "不定时抢购" : "")布防"))
                        .font(.system(size: 20, weight: .semibold))
                    Text(confirm ? "最后核对一次" : mode.blurb)
                        .font(.system(size: 11)).foregroundStyle(AppPalette.muted)
                }
                Spacer()
                Button("关闭") { dismiss() }.disabled(m.busy || working)
            }
            if confirm { confirmation } else { form }
        }
        .padding(28)
        .frame(width: 520)
        .background(AppPalette.background)
        .buttonStyle(CardButtonStyle())
        .preferredColorScheme(.dark)
        .errorToast(topInset: 64)
        .task(id: m.root) {
            settingsLoaded = false
            do {
                let result = try await m.backend.run(["settings"])
                settings = dictValue(result["settings"]).reduce(into: [:]) { values, entry in
                    if let number = entry.value as? NSNumber { values[entry.key] = number.intValue }
                }
                if mode == .redemption {
                    date = quotaTimes.map { nextQuotaDate($0, after: Date().addingTimeInterval(Double(prep + 2) * 60)) }.min() ?? date
                    let formatter = DateFormatter(); formatter.dateFormat = "HH:mm"
                    timeChoice = formatter.string(from: date)
                }
                settingsRevision = result["settings_revision"] as? String ?? ""
                settingsLoaded = !settingsRevision.isEmpty
            } catch { m.message = error.localizedDescription }
        }
        .onChange(of: dry) { value in
            if !value && !drillOnly { now = false }
        }
    }

    private var form: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top, spacing: 14) {
                field("产品代码", $code, "如 JX040229")
                field("购买金额", $amount, "上限 50000 元")
            }
            if mode == .redemption {
                HStack {
                    Picker("开始盯盘时间", selection: $timeChoice) {
                        ForEach(quotaTimes, id: \.self) { Text($0).tag($0) }
                        Text("自定义").tag("custom")
                    }
                    .onChange(of: timeChoice) { value in
                        if value != "custom" {
                            date = nextQuotaDate(value, after: Date().addingTimeInterval(Double(prep + 2) * 60))
                        }
                    }
                    if timeChoice == "custom" {
                        DatePicker("自定义时间", selection: $date,
                                   displayedComponents: [.date, .hourAndMinute])
                            .labelsHidden()
                    } else {
                        Text(date.formatted(date: .abbreviated, time: .omitted))
                            .font(.system(size: 11)).foregroundStyle(AppPalette.muted)
                    }
                }
                .disabled(now)
                Text("每天这些时间左右可能放出额度，不保证准时；其他日期和时间请选择自定义。")
                    .font(.system(size: 11)).foregroundStyle(AppPalette.muted)
            } else {
                DatePicker("开售时间", selection: $date, displayedComponents: [.date, .hourAndMinute])
                    .disabled(now)
            }
            VStack(alignment: .leading, spacing: 5) {
                Text("当前配置").font(.caption).foregroundStyle(AppPalette.muted)
                Text(settingsLoaded ? configuration : "正在读取设置…")
                    .font(.system(size: 12)).foregroundStyle(AppPalette.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if drillOnly {
                Toggle("实际付款：输入交易密码并提交", isOn: Binding(
                    get: { !dry }, set: { dry = !$0 }))
                Text(dry ? "默认只到密码页，不输入密码、不提交。"
                         : "将按填写金额实际购买一笔，下一步需再次输入金额确认。")
                    .font(.system(size: 12)).foregroundStyle(dry ? AppPalette.muted : AppPalette.warn)
            } else {
                Toggle("演练：只到密码页，不输入密码、不提交", isOn: $dry)
            }
            Toggle(drillOnly ? "立即开始（约三分钟后购买）" : "立即排练", isOn: $now)
                .disabled(!dry && !drillOnly)
            if m.busy || working { busyLine }
            HStack(spacing: 10) {
                Spacer()
                Button("取消") { dismiss() }.disabled(m.busy || working)
                Button("下一步") {
                    guard let problem = formProblem else {
                        confirmAmount = ""
                        confirm = true
                        return
                    }
                    m.message = problem
                }
                .buttonStyle(CardButtonStyle(primary: true))
                .disabled(m.busy || !settingsLoaded)
            }
        }
    }

    private var confirmation: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(summary)
                .font(.system(size: 13))
                .fixedSize(horizontal: false, vertical: true)
            if !dry {
                VStack(alignment: .leading, spacing: 8) {
                    Text("再输入一次金额").font(.caption).foregroundStyle(AppPalette.muted)
                    TextField("金额", text: $confirmAmount).cardField()
                }
            }
            Text("一笔只提交一次；结果以银行交易记录为准。提交后不再重试。")
                .font(.system(size: 11)).foregroundStyle(AppPalette.muted)
            if m.busy || working { busyLine }
            HStack(spacing: 10) {
                Spacer()
                Button("返回") { confirm = false; m.message = nil }
                Button { submit() } label: {
                    HStack(spacing: 7) {
                        if m.busy || working { ProgressView().controlSize(.small) }
                        Text(dry ? "开始演练" : "确认真实布防")
                    }
                }
                    .buttonStyle(CardButtonStyle(primary: true))
                    .disabled(m.busy || working || (!dry && confirmAmount != amount))
            }
        }
    }

    private var prep: Int { settings["cold_start_minutes"] ?? 7 }
    private var window: Int { settings["irregular_window_minutes"] ?? 5 }
    private var configuration: String {
        let common = "提前 \(prep) 分钟冷启动，登录后进入购买页等待。"
        if mode == .redemption {
            return common + "首次查询提前 \(settings["irregular_advance_ms"] ?? 200) ms；"
                + "无额度后间隔 \(settings["irregular_retry_min_ms"] ?? 50)–\(settings["irregular_retry_max_ms"] ?? 250) ms，最长 \(window) 分钟。"
        }
        return common + "首次查询延后 \(settings["first_offset_ms"] ?? 200) ms；"
            + "无额度后最多再重试 \(settings["first_max_retries"] ?? 5) 次。"
    }

    private var summary: String {
        let when = now ? "约三分钟后" : date.formatted(date: .abbreviated, time: .shortened)
        let action = dry ? "演练到密码页" : "提交一次"
        if mode == .redemption {
            return "产品 \(code.trimmingCharacters(in: .whitespaces))，\(when) 起 \(window) 分钟"
                + "窗口内在同一购买页查询，有额度就\(action) \(amount) 元。\n\(configuration)"
        }
        return "产品 \(code.trimmingCharacters(in: .whitespaces))，\(when) \(action) \(amount) 元。\n\(configuration)"
    }

    private var busyLine: some View {
        HStack(spacing: 8) {
            ProgressView().controlSize(.small)
            Text(step ?? (m.busyLabel.isEmpty ? "处理中…" : m.busyLabel))
                .font(.system(size: 11)).foregroundStyle(AppPalette.accent)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func field(_ title: String, _ text: Binding<String>, _ placeholder: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.caption).foregroundStyle(AppPalette.muted)
            TextField(placeholder, text: text).cardField()
        }
    }

    private var formProblem: String? {
        if !validCode(code.trimmingCharacters(in: .whitespaces)) { return "产品代码须为 4–20 位字母或数字。" }
        if !validAmount(amount) { return "金额须为 0–50000 元，最多两位小数。" }
        if now && !dry && !drillOnly { return "立即排练只能使用演练。" }
        if !now && date <= Date().addingTimeInterval(Double(prep + 2) * 60) {
            return "\(mode == .redemption ? "额度放出时间" : "开售时间")至少要在 \(prep + 2) 分钟之后。"
        }
        return nil
    }

    private func submit() {
        if let problem = formProblem {
            m.message = problem
            confirm = false
            return
        }
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        var args = ["arm", "--code", code.trimmingCharacters(in: .whitespaces),
                    "--amount", amount, "--settings-revision", settingsRevision]
        args += now ? ["--now"] : ["--at", formatter.string(from: date)]
        if mode == .redemption {
            args += ["--mode", "redemption"]
        }
        if dry { args.append("--dry-run") }
        if now && !dry { args.append("--confirm-real-payment") }
        working = true
        Task { await armWithAutoStart(args) }
    }

    /// Arm once. If the only problem is a stopped emulator, start it here — the
    /// confirmation button keeps spinning and the sheet says what is happening
    /// — then arm again. Any other failure is reported as before.
    private func armWithAutoStart(_ args: [String]) async {
        defer { working = false }
        let label = dry ? "演练布防" : "真实布防"
        step = dry ? "正在布防（演练）…" : "正在布防…"
        var ok = await m.action(args, label: label)
        if !ok, let message = m.message, message.contains("模拟器没有在运行") {
            step = "模拟器未运行，正在启动（约 20–40 秒）…"
            if await m.action(["emulator", "start"], label: "启动模拟器") {
                step = "模拟器已启动，正在重新布防…"
                ok = await m.action(args, label: label)
            } else {
                step = nil
                m.message = m.message ?? "模拟器启动失败。"
                return
            }
        }
        step = nil
        if ok {
            dismiss()
        } else {
            m.message = m.message ?? "操作未完成，请稍后重试。"
        }
    }
}
