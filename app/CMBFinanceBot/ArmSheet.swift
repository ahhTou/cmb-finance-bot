import SwiftUI

enum ArmMode: String {
    case firstLaunch = "first_launch"
    case redemption = "redemption"

    var title: String { self == .redemption ? "赎回抢购" : "首发" }
    var blurb: String {
        self == .redemption
            ? "赎回抢购模式 · 有额度才提交，一笔只提交一次"
            : "首发模式 · 一笔只提交一次"
    }
}

private func armDefaultDate(_ mode: ArmMode) -> Date {
    let tomorrow = Calendar.current.date(byAdding: .day, value: 1, to: Date()) ?? Date()
    let hour = mode == .redemption ? 0 : 9
    let minute = mode == .redemption ? 15 : 0
    return Calendar.current.date(bySettingHour: hour, minute: minute, second: 0, of: tomorrow) ?? tomorrow
}

struct ArmSheet: View {
    @EnvironmentObject var m: Model
    @Environment(\.dismiss) private var dismiss
    let drillOnly: Bool
    let mode: ArmMode

    @State private var code = ""
    @State private var amount = ""
    @State private var date: Date
    @State private var prep = 15
    @State private var window = 3
    @State private var dry = false
    @State private var now = false
    @State private var confirm = false
    @State private var confirmAmount = ""
    @State private var error: String?
    @State private var step: String?
    @State private var working = false

    init(drill: Bool = false, mode: ArmMode = .firstLaunch) {
        self.drillOnly = drill
        self.mode = mode
        _date = State(initialValue: armDefaultDate(mode))
        _dry = State(initialValue: drill)
        _now = State(initialValue: drill)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack(alignment: .center) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(confirm ? "确认布防"
                         : (drillOnly ? "演练布防" : "新建\(mode == .redemption ? "赎回抢购" : "")布防"))
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
            DatePicker(mode == .redemption ? "额度放出时间" : "开售时间",
                       selection: $date, displayedComponents: [.date, .hourAndMinute])
                .disabled(now)
            HStack {
                Stepper("提前 \(prep) 分钟准备", value: $prep, in: 5...15)
                Spacer()
                if mode == .redemption {
                    Stepper("窗口 \(window) 分钟", value: $window, in: 1...60)
                } else {
                    Text("200ms 由脚本自动加").font(.system(size: 11)).foregroundStyle(AppPalette.muted)
                }
            }
            if mode == .redemption {
                HStack(spacing: 7) {
                    Image(systemName: "arrow.triangle.2.circlepath")
                    Text("窗口内反复打开购买页；出现购买表单才提交，没有额度不提交")
                }.font(.system(size: 11)).foregroundStyle(AppPalette.muted)
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
            if let error {
                Text(error).font(.system(size: 11)).foregroundStyle(AppPalette.accent)
            }
            HStack(spacing: 10) {
                Spacer()
                Button("取消") { dismiss() }.disabled(m.busy || working)
                Button("下一步") {
                    guard let problem = formProblem else {
                        confirmAmount = ""
                        confirm = true
                        return
                    }
                    error = problem
                }
                .buttonStyle(CardButtonStyle(primary: true))
                .disabled(m.busy)
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
            if let error {
                Text(error).font(.system(size: 11)).foregroundStyle(AppPalette.accent)
            }
            HStack(spacing: 10) {
                Spacer()
                Button("返回") { confirm = false; error = nil }
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

    private var summary: String {
        let when = now ? "约三分钟后" : date.formatted(date: .abbreviated, time: .shortened)
        let action = dry ? "演练到密码页" : "提交一次"
        if mode == .redemption {
            return "产品 \(code.trimmingCharacters(in: .whitespaces))，\(when) 起 \(window) 分钟"
                + "窗口内反复打开购买页，有额度就\(action) \(amount) 元。"
        }
        return "产品 \(code.trimmingCharacters(in: .whitespaces))，\(when) \(action) \(amount) 元。"
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
        if mode == .redemption && !(1...60).contains(window) { return "窗口须为 1–60 分钟。" }
        if now && !dry && !drillOnly { return "立即排练只能使用演练。" }
        if !now && date <= Date().addingTimeInterval(Double(prep + 2) * 60) {
            return "\(mode == .redemption ? "额度放出时间" : "开售时间")至少要在 \(prep + 2) 分钟之后。"
        }
        return nil
    }

    private func submit() {
        if let problem = formProblem {
            error = problem
            confirm = false
            return
        }
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        var args = ["arm", "--code", code.trimmingCharacters(in: .whitespaces),
                    "--amount", amount, "--prep-minutes", String(prep)]
        args += now ? ["--now"] : ["--at", formatter.string(from: date)]
        if mode == .redemption {
            args += ["--mode", "redemption", "--window-minutes", String(window)]
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
                error = m.message ?? "模拟器启动失败。"
                return
            }
        }
        step = nil
        if ok {
            dismiss()
        } else {
            error = m.message ?? "操作未完成，请稍后重试。"
        }
    }
}
