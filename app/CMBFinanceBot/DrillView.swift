import SwiftUI

struct DrillView: View {
    @EnvironmentObject var m: Model
    @State private var code = ""
    @State private var amount = "0.01"
    @State private var cancelAmount = "0.01"
    @State private var limit = 1
    @State private var allOrders = false
    @State private var showArm = false
    @State private var confirmCancel = false
    @State private var showOutput = false
    @State private var realBuy = false
    @State private var confirmBuy = false
    @State private var buyCode = ""
    @State private var buyAmount = ""
    @State private var confirmBuyAmount = ""

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                EqualHeightColumns(spacing: 14) {
                    drillCard
                    deviceCard
                }
                EqualHeightColumns(spacing: 14) {
                    cancelCard
                    notesCard
                }
            }
            .padding(.horizontal, 26)
        }
        .sheet(isPresented: $showArm) { ArmSheet(drill: true).environmentObject(m) }
        .sheet(isPresented: $confirmCancel) { cancelConfirmation }
        .sheet(isPresented: $showOutput) { outputSheet }
        .sheet(isPresented: $confirmBuy) { buyConfirmation }
    }

    private var drillCard: some View {
        Card("演练布防", subtitle: "走完整冷启动、登录、购买流程", fillHeight: true) {
            VStack(alignment: .leading, spacing: 12) {
                Text("默认到密码页停止，也可选择实际付款并确认金额；支持立即开始或指定开售时间。")
                    .font(.system(size: 11)).foregroundStyle(AppPalette.muted)
                    .fixedSize(horizontal: false, vertical: true)
                Button("打开演练布防") { showArm = true }
                    .buttonStyle(CardButtonStyle(primary: true))
                    .disabled(m.busy || m.active)
                Divider().overlay(Color.white.opacity(0.05))
                Text("单笔购买演练").font(.system(size: 12, weight: .medium))
                HStack(alignment: .top, spacing: 10) {
                    field("产品代码", $code, "如 JX040229")
                    field("金额", $amount, "0.01")
                }
                FavoritePicker(code: $code)
                Toggle("实际付款：输入交易密码并提交", isOn: $realBuy)
                    .disabled(m.busy || m.active)
                Text(realBuy ? "立即购买一笔，不创建值守任务；下一步需确认金额。"
                             : "只到密码页停止，不输入密码、不提交。")
                    .font(.system(size: 11)).foregroundStyle(realBuy ? AppPalette.warn : AppPalette.muted)
                HStack(spacing: 8) {
                    Button(realBuy ? "直接购买…" : "单笔购买演练") { runBuy() }
                        .disabled(m.busy || m.active || !validCode(code.trimmingCharacters(in: .whitespaces)) || !validAmount(amount))
                    Button("命令输出") { showOutput = true }
                }
            }
        }
    }

    private var deviceCard: some View {
        Card("设备操作", subtitle: "只操作项目专用模拟器", fillHeight: true) {
            VStack(alignment: .leading, spacing: 12) {
                MetricGrid {
                    Metric("模拟器", m.device.isEmpty ? "尚未刷新" : (emulatorRunning ? "运行中" : "未运行"))
                    Metric("开机", m.device.isEmpty ? "尚未刷新" : (emulatorRunning ? (boolValue(m.device["booted"]) == true ? "已完成" : "未完成") : "未运行"))
                    Metric("App 进程", emulatorRunning ? (stringValue(m.device["app_pid"]) ?? "—") : "—")
                    Metric("画面", emulatorRunning ? (boolValue(m.device["awake"]) == true ? "Awake" : "未知") : "—")
                }
                Spacer(minLength: 6)
                HStack(spacing: 8) {
                    Button("启动") { Task { await m.action(["emulator", "start"], label: "启动模拟器") } }
                        .disabled(m.busy || m.active)
                    Button("关闭") { Task { await m.action(["emulator", "stop"], label: "关闭模拟器") } }
                        .disabled(m.busy || m.active)
                    Button("恢复常亮") { Task { await m.action(["keep-awake"], label: "恢复常亮") } }
                        .disabled(m.busy)
                }
                HStack(spacing: 8) {
                    Button("截图") { Task { await m.action(["screenshot"], label: "截取画面") } }
                        .disabled(m.busy)
                    Button("刷新设备") { Task { await m.loadDevice() } }
                        .disabled(m.busy)
                }
                if m.active {
                    Text("值守活动期间不能启动或关闭模拟器。")
                        .font(.system(size: 10)).foregroundStyle(AppPalette.muted)
                }
            }
        }
    }

    private var cancelCard: some View {
        Card("撤单", subtitle: "处理交易记录里可撤单的测试订单", fillHeight: true) {
            VStack(alignment: .leading, spacing: 12) {
                Text("先查看可撤单数量，再决定演练或真实撤单。真实撤单会输入交易密码并提交。")
                    .font(.system(size: 11)).foregroundStyle(AppPalette.muted)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(alignment: .top, spacing: 10) {
                    field("订单金额", $cancelAmount, "0.01")
                    VStack(alignment: .leading, spacing: 8) {
                        Text("最多撤几笔").font(.caption).foregroundStyle(AppPalette.muted)
                        Stepper(allOrders ? "全部" : "最多 \(limit) 笔", value: $limit, in: 1...20)
                            .disabled(allOrders)
                    }
                }
                Toggle("全部可撤单（不限笔数）", isOn: $allOrders)
                HStack(spacing: 8) {
                    Button("查看可撤单") { runCancel(list: true) }
                        .disabled(m.busy || m.active || !validAmount(cancelAmount))
                    Button("撤单演练") { runCancel(dry: true) }
                        .disabled(m.busy || m.active || !validAmount(cancelAmount))
                    Button("真实撤单") { confirmCancel = true }
                        .buttonStyle(CardButtonStyle(primary: true))
                        .disabled(m.busy || m.active || !validAmount(cancelAmount))
                }
                if m.active {
                    Text("值守活动期间不能撤单；先取消当前布防。")
                        .font(.system(size: 10)).foregroundStyle(AppPalette.warn)
                }
                HStack {
                    Text("结果不明时先查交易记录，不要重复撤单。")
                        .font(.system(size: 10)).foregroundStyle(AppPalette.muted)
                    Spacer()
                    Button("查看输出") { showOutput = true }
                }
            }
        }
    }

    private var notesCard: some View {
        Card("常用命令", subtitle: "终端里的等价入口，可直接复制", fillHeight: true) {
            VStack(alignment: .leading, spacing: 10) {
                commandRow("python3 -B src/night_watch.py status")
                commandRow("python3 -B src/night_watch.py disarm")
                commandRow("python3 -B src/cancel_orders.py --list")
                commandRow("python3 -B src/fast_buy_uia2.py --code <代码> --amount <金额> --dry-run")
                Spacer(minLength: 6)
                Text("真实布防、撤单和凭据修改须经用户明确确认后执行。")
                    .font(.system(size: 10)).foregroundStyle(AppPalette.muted)
            }
        }
    }

    private var outputSheet: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("命令输出").font(.system(size: 17, weight: .semibold))
                Spacer()
                Button("复制") { copyText(m.commandOutput.joined(separator: "\n")) }
                    .disabled(m.commandOutput.isEmpty)
                Button("关闭") { showOutput = false }
            }
            if m.commandOutput.isEmpty {
                Text("运行演练、购买演练或撤单命令后，这里显示文本输出。")
                    .font(.system(size: 12)).foregroundStyle(AppPalette.muted)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            } else {
                LogText(lines: m.commandOutput)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .padding(10)
                    .background(AppPalette.input, in: RoundedRectangle(cornerRadius: 8))
            }
            Text("撤单结果以银行交易记录为准；结果不明时不要重试。")
                .font(.system(size: 10)).foregroundStyle(AppPalette.muted)
        }
        .padding(24).frame(width: 760, height: 560)
        .background(AppPalette.background).buttonStyle(CardButtonStyle()).preferredColorScheme(.dark)
    }

    private var cancelConfirmation: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("确认真实撤单").font(.system(size: 20, weight: .semibold))
            Text("金额 \(cancelAmount) 元的可撤单订单，最多撤 \(limitText) 笔。会输入交易密码并提交，操作后立即查交易记录。")
                .font(.system(size: 13)).fixedSize(horizontal: false, vertical: true)
            Text("一笔只提交一次；结果不明时不要重试。")
                .font(.system(size: 11)).foregroundStyle(AppPalette.accent)
            HStack(spacing: 10) {
                Spacer()
                Button("取消") { confirmCancel = false }
                Button("确认撤单") {
                    confirmCancel = false
                    runCancel()
                }.buttonStyle(CardButtonStyle(primary: true))
            }
        }
        .padding(28).frame(width: 460).background(AppPalette.background)
        .buttonStyle(CardButtonStyle()).preferredColorScheme(.dark)
    }

    private var buyConfirmation: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("确认真实单笔购买").font(.system(size: 20, weight: .semibold))
            Text("现在购买产品 \(buyCode)，金额 \(buyAmount) 元。将输入交易密码并提交一次。")
                .font(.system(size: 13)).fixedSize(horizontal: false, vertical: true)
            Text("再输入一次金额").font(.caption).foregroundStyle(AppPalette.muted)
            TextField("金额", text: $confirmBuyAmount).cardField()
            Text("结果以银行交易记录为准；结果不明时先核对，不要重复购买。")
                .font(.system(size: 11)).foregroundStyle(AppPalette.warn)
            HStack(spacing: 10) {
                Spacer()
                Button("取消") { confirmBuy = false }
                Button("确认实际付款") {
                    confirmBuy = false
                    executeBuy(code: buyCode, amount: buyAmount, real: true)
                }
                .buttonStyle(CardButtonStyle(primary: true))
                .disabled(m.busy || m.active || confirmBuyAmount != buyAmount)
            }
        }
        .padding(28).frame(width: 480).background(AppPalette.background)
        .buttonStyle(CardButtonStyle()).preferredColorScheme(.dark)
    }

    private func field(_ title: String, _ text: Binding<String>, _ placeholder: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.caption).foregroundStyle(AppPalette.muted)
            TextField(placeholder, text: text).cardField()
        }
    }

    private func commandRow(_ text: String) -> some View {
        HStack(spacing: 8) {
            Text(text)
                .font(.system(size: 10, design: .monospaced))
                .foregroundStyle(Color(white: 0.78))
                .lineLimit(1).minimumScaleFactor(0.7)
                .textSelection(.enabled)
            Spacer(minLength: 4)
            Button { copyText(text) } label: {
                Image(systemName: "doc.on.doc").font(.system(size: 10))
            }.buttonStyle(.plain).foregroundStyle(AppPalette.muted).pointingHand()
        }
    }

    private func runBuy() {
        let trimmed = code.trimmingCharacters(in: .whitespaces)
        guard validCode(trimmed), validAmount(amount) else {
            m.message = "产品代码或金额格式不正确。"
            return
        }
        m.message = nil
        if realBuy {
            buyCode = trimmed
            buyAmount = amount
            confirmBuyAmount = ""
            confirmBuy = true
        } else {
            executeBuy(code: trimmed, amount: amount, real: false)
        }
    }

    private func executeBuy(code: String, amount: String, real: Bool) {
        Task {
            let ok = await m.action(["buy", "--code", code, "--amount", amount,
                                     real ? "--confirm-real-payment" : "--dry-run"],
                                    label: real ? "真实单笔购买" : "单笔购买演练")
            if ok { showOutput = true }
        }
    }

    private func runCancel(list: Bool = false, dry: Bool = false) {
        guard validAmount(cancelAmount) else { return }
        var args = ["cancel", "--amount", cancelAmount]
        if !allOrders { args += ["--limit", String(limit)] }
        if list { args.append("--list") }
        else if dry { args.append("--dry-run") }
        else { args.append("--yes") }
        Task { await m.action(args, label: list ? "查看可撤单" : dry ? "撤单演练" : "真实撤单") }
    }

    private var emulatorRunning: Bool {
        boolValue(dictValue(m.device["emulator"])["running"]) == true
    }

    private var limitText: String {
        allOrders ? "全部" : "\(limit)"
    }
}
