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
