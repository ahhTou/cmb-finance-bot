import SwiftUI

private func armDefaultDate() -> Date {
    let tomorrow = Calendar.current.date(byAdding: .day, value: 1, to: Date()) ?? Date()
    return Calendar.current.date(bySettingHour: 9, minute: 0, second: 0, of: tomorrow) ?? tomorrow
}

struct ArmSheet: View {
    @EnvironmentObject var m: Model
    @Environment(\.dismiss) private var dismiss
    let drillOnly: Bool

    @State private var code = ""
    @State private var amount = ""
    @State private var date = armDefaultDate()
    @State private var prep = 15
    @State private var dry = false
    @State private var now = false
    @State private var confirm = false
    @State private var confirmAmount = ""
    @State private var error: String?

    init(drill: Bool = false) {
        self.drillOnly = drill
        _dry = State(initialValue: drill)
        _now = State(initialValue: drill)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack(alignment: .center) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(confirm ? "确认布防" : (drillOnly ? "演练布防" : "新建布防"))
                        .font(.system(size: 20, weight: .semibold))
                    Text(confirm ? "最后核对一次" : "首发模式 · 一笔只提交一次")
                        .font(.system(size: 11)).foregroundStyle(AppPalette.muted)
                }
                Spacer()
                Button("关闭") { dismiss() }.disabled(m.busy)
            }
            if confirm { confirmation } else { form }
        }
        .padding(28)
        .frame(width: 520)
        .background(AppPalette.background)
        .buttonStyle(CardButtonStyle())
        .preferredColorScheme(.dark)
        .onChange(of: dry) { value in
            if !value { now = false }
        }
    }

    private var form: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top, spacing: 14) {
                field("产品代码", $code, "如 JX040229")
                field("购买金额", $amount, "上限 50000 元")
            }
            DatePicker("开售时间", selection: $date, displayedComponents: [.date, .hourAndMinute])
                .disabled(now)
            HStack {
                Stepper("提前 \(prep) 分钟准备", value: $prep, in: 5...15)
                Spacer()
                Text("200ms 由脚本自动加").font(.system(size: 11)).foregroundStyle(AppPalette.muted)
            }
            if drillOnly {
                HStack(spacing: 7) {
                    Image(systemName: "testtube.2")
                    Text("演练：只到密码页，不输入密码、不提交")
                }.font(.system(size: 12)).foregroundStyle(AppPalette.muted)
            } else {
                Toggle("演练：只到密码页，不输入密码、不提交", isOn: $dry)
            }
            Toggle("立即排练", isOn: $now).disabled(!dry)
            if let error {
                Text(error).font(.system(size: 11)).foregroundStyle(AppPalette.accent)
            }
            HStack(spacing: 10) {
                Spacer()
                Button("取消") { dismiss() }
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
            Text("产品 \(code.trimmingCharacters(in: .whitespaces))，\(now ? "约三分钟后" : date.formatted(date: .abbreviated, time: .shortened)) \(dry ? "演练" : "真实提交一次") \(amount) 元。")
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
            if let error {
                Text(error).font(.system(size: 11)).foregroundStyle(AppPalette.accent)
            }
            HStack(spacing: 10) {
                Spacer()
                Button("返回") { confirm = false; error = nil }
                Button(dry ? "开始演练" : "确认真实布防") { submit() }
                    .buttonStyle(CardButtonStyle(primary: true))
                    .disabled(m.busy || (!dry && confirmAmount != amount))
            }
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
        if now && !dry { return "立即排练只能使用演练。" }
        if !now && date <= Date().addingTimeInterval(Double(prep + 2) * 60) {
            return "开售时间至少要在 \(prep + 2) 分钟之后。"
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
        if dry { args.append("--dry-run") }
        Task {
            let ok = await m.action(args, label: dry ? "演练布防" : "真实布防")
            if ok {
                dismiss()
            } else {
                error = m.message ?? "操作未完成，请稍后重试。"
            }
        }
    }
}
