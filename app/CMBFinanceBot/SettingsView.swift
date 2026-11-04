import SwiftUI

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
                PurchaseRetrySettingsCard()
                Card("凭据状态", subtitle: "这里只同步脚本保存的值，不会修改银行 App 中的设置。") {
                    HStack { Detail("登录与交易凭据", m.credentialState); Detail("邮件通知", m.mailConfigured ? "已配置" : "未配置") }
                }
                EqualHeightColumns {
                    Card("九宫格图案", subtitle: "先在银行 App 修改，再到这里同步", fillHeight: true) {
                        VStack(spacing: 18) {
                            Text(second ? "再次点选相同图案" : "点选 4–9 个不重复的点")
                                .font(.system(size: 12)).foregroundStyle(AppPalette.muted)
                            ForEach(0..<3) { row in
                                HStack(spacing: 24) {
                                    ForEach(1..<4) { col in
                                        let point = String(row * 3 + col)
                                        Button {
                                            if second {
                                                if !repeated.contains(point) { repeated += point }
                                            } else {
                                                if !pattern.contains(point) { pattern += point }
                                            }
                                        } label: {
                                            Circle()
                                                .fill((second ? repeated : pattern).contains(point) ? AppPalette.accent : Color(white: 0.38))
                                                .frame(width: 27, height: 27)
                                                .frame(width: 36, height: 36)
                                        }
                                        .buttonStyle(.plain)
                                        .pointingHand(!m.credentialsDisabled && !m.busy)
                                        .accessibilityLabel("第 \(point) 个点")
                                        .accessibilityValue((second ? repeated : pattern).contains(point) ? "已选" : "未选")
                                    }
                                }
                            }
                            Text("已选 \((second ? repeated : pattern).count) 个点")
                                .font(.caption).foregroundStyle(AppPalette.muted)
                            HStack {
                                Button("重画") { pattern = ""; repeated = ""; second = false }
                                if !second {
                                    Button("再画一次") { second = true }.disabled(pattern.count < 4)
                                } else {
                                    Button("保存图案") {
                                        let value = pattern
                                        pattern = ""; repeated = ""; second = false
                                        Task { await m.action(["set-login-pattern"], input: ["new": value]) }
                                    }.disabled(pattern != repeated || pattern.count < 4)
                                }
                            }
                        }
                        .frame(maxWidth: .infinity).padding(.vertical, 8)
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
                        }
                        .buttonStyle(CardButtonStyle(primary: true))
                        .disabled(password != again || !valid(password) || !valid(current))
                    }
                }
            }
            .padding(.horizontal, 26)
        }
        .disabled(m.credentialsDisabled || m.busy)
        .onDisappear {
            pattern = ""; repeated = ""; current = ""; password = ""; again = ""; second = false
        }
    }

    private func valid(_ value: String) -> Bool {
        value.count == 6 && value.utf8.allSatisfy { (48...57).contains($0) }
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

private struct PurchaseRetrySettingsCard: View {
    @EnvironmentObject var m: Model
    @State private var values: [String: String] = [:]
    @State private var loaded = false
    @State private var saved = false

    private let common = [("cold_start_minutes", "冷启动提前 E（分钟）", 7)]
    private let first = [("first_offset_ms", "首次查询延后 N（ms）", 200),
                         ("first_max_retries", "首次之外最多重试 M（次）", 5)]
    private let irregular = [("irregular_advance_ms", "首次查询提前 N（ms）", 200),
                             ("irregular_window_minutes", "最长查询窗口 M（分钟）", 5),
                             ("irregular_retry_min_ms", "随机重试间隔 R1（ms）", 50),
                             ("irregular_retry_max_ms", "随机重试间隔 R2（ms）", 250)]
    private let direct = [("reopen_deadline", "直接购买总时限（秒）", 60),
                          ("drill_form_deadline", "单笔购买演练总时限（秒）", 10)]
    private var all: [(String, String, Int)] { common + first + irregular + direct }
    private var valid: Bool {
        let ranges: [String: ClosedRange<Int>] = [
            "cold_start_minutes": 1...60, "first_offset_ms": 0...10000,
            "first_max_retries": 0...100, "irregular_advance_ms": 0...10000,
            "irregular_window_minutes": 1...60, "irregular_retry_min_ms": 1...60000,
            "irregular_retry_max_ms": 1...60000, "reopen_deadline": 1...300,
            "drill_form_deadline": 1...300]
        for (key, _, _) in all {
            guard let value = Int(values[key] ?? ""), ranges[key]?.contains(value) == true else { return false }
        }
        return Int(values["irregular_retry_min_ms"] ?? "")! <= Int(values["irregular_retry_max_ms"] ?? "")!
    }

    var body: some View {
        Card("值守配置", subtitle: "新布防使用当前配置；已布防任务保持原值") {
            fields("通用", common)
            fields("首发模式", first)
            Text("M 为首次之外的重试次数，默认最多查询 6 次；无额度时立即串行重试。")
                .font(.caption).foregroundStyle(AppPalette.muted)
            fields("不定时抢购模式", irregular)
            Text("首次查询在设定时间之前发出；无额度后随机等待 R1–R2 ms，窗口从首次计划查询时间计算。")
                .font(.caption).foregroundStyle(AppPalette.muted)
            fields("单笔购买", direct)
            HStack {
                if saved { Text("配置已保存").font(.caption).foregroundStyle(AppPalette.muted) }
                Spacer()
                Button("保存值守配置") {
                    var args = ["settings"]
                    for (key, _, _) in all {
                        args += ["--" + key.replacingOccurrences(of: "_", with: "-"), values[key] ?? ""]
                    }
                    Task { saved = await m.action(args, label: "保存值守配置") }
                }
                .buttonStyle(CardButtonStyle(primary: true))
                .disabled(!loaded || !valid || m.busy)
            }
        }
        .disabled(!loaded || m.busy)
        .onChange(of: values) { _ in saved = false }
        .task(id: m.root) {
            loaded = false; saved = false
            guard !m.root.isEmpty else { return }
            do {
                let result = try await m.backend.run(["settings"])
                let settings = dictValue(result["settings"])
                for (key, _, initial) in all {
                    values[key] = String((settings[key] as? NSNumber)?.intValue ?? initial)
                }
                loaded = true
            } catch { m.message = error.localizedDescription }
        }
    }

    private func fields(_ title: String, _ rows: [(String, String, Int)]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.system(size: 13, weight: .semibold))
            ForEach(rows, id: \.0) { key, label, initial in
                HStack {
                    Text(label).font(.caption).foregroundStyle(AppPalette.muted)
                    Spacer()
                    TextField(String(initial), text: Binding(
                        get: { values[key] ?? "" }, set: { values[key] = $0 }))
                        .cardField().frame(width: 110)
                }
            }
        }
    }
}
