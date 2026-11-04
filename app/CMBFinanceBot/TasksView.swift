import SwiftUI

struct TasksView: View {
    @EnvironmentObject var m: Model
    @Binding var tab: Int
    @State private var showArm = false
    @State private var armMode: ArmMode = .firstLaunch
    @State private var confirmDisarm = false

    private var taskMode: String { m.task["mode"] as? String ?? "first_launch" }
    private var firstLaunchActive: Bool { m.active && taskMode != "redemption" }
    private var redemptionActive: Bool { m.active && taskMode == "redemption" }

    var body: some View {
        GeometryReader { geo in
            let spacing: CGFloat = 14
            let height = max(180, (geo.size.height - spacing * 2) / 3)
            ScrollView {
                VStack(spacing: spacing) {
                    firstLaunch.frame(height: height)
                    placeholder(icon: "arrow.triangle.2.circlepath",
                                title: "捡漏模式",
                                text: "白天轮询多只理财，有人撤单、额度重新放出时自动买入。",
                                features: ["反复查看多只理财", "按可购额度比例买入", "白天运行，可设终止时间"],
                                tint: Color(red: 0.35, green: 0.62, blue: 0.95))
                        .frame(height: height)
                    redemption.frame(height: height)
                }
                .padding(.horizontal, 26)
                .frame(maxWidth: .infinity, alignment: .top)
            }
        }
        .sheet(isPresented: $showArm) { ArmSheet(mode: armMode).environmentObject(m) }
        .alert("取消当前布防？", isPresented: $confirmDisarm) {
            Button("继续值守", role: .cancel) {}
            Button("确认取消", role: .destructive) {
                Task { await m.action(["disarm"], label: "取消布防") }
            }
        } message: {
            Text("取消后本轮不会再提交；已经发生的交易仍要查交易记录。")
        }
    }

    // MARK: 首发

    private var firstLaunch: some View {
        ModeCard(icon: "bolt.fill", tint: AppPalette.accent, title: "首发模式",
                 subtitle: "开售准点抢一只新发理财",
                 badge: Badge(text: m.active && !firstLaunchActive ? "其他值守中" : "可用",
                              color: m.active && !firstLaunchActive ? AppPalette.warn : AppPalette.good)) {
            if firstLaunchActive {
                activeSummary(redemption: false)
            } else {
                VStack(alignment: .leading, spacing: 7) {
                    Text("按配置冷启动并登录，提前进入购买页等待；到点查询，有额度才提交一次。")
                        .font(.system(size: 11)).foregroundStyle(AppPalette.muted)
                        .fixedSize(horizontal: false, vertical: true)
                    feature("clock", "冷启动提前量在设置中配置")
                    feature("bolt.fill", "默认开售 +200ms 首次查询，最多再重试 5 次")
                    feature("checkmark.shield", "只提交一次，失败不重试")
                    if !m.task.isEmpty && taskMode != "redemption" {
                        Text("上次任务已结束 · \(phaseName(m.phase))")
                            .font(.system(size: 10)).foregroundStyle(AppPalette.muted)
                    }
                }
            }
        } actions: {
            if firstLaunchActive {
                Button("刷新") { Task { await m.refresh() } }.disabled(m.busy)
                Button("取消布防") { confirmDisarm = true }
                    .disabled(m.busy || m.phase == "firing")
            } else {
                Button("新建布防") { armMode = .firstLaunch; showArm = true }
                    .buttonStyle(CardButtonStyle(primary: true))
                    .disabled(m.active)
                Button("查看历史") { tab = 3 }
            }
        }
    }

    // MARK: 不定时抢购

    private var redemption: some View {
        ModeCard(icon: "clock.arrow.circlepath", tint: Color(red: 0.72, green: 0.45, blue: 0.95),
                 title: "不定时抢购模式", subtitle: "常用时间盯盘，有额度就买",
                 badge: Badge(text: redemptionActive ? phaseName(m.phase)
                                       : (m.active ? "其他值守中" : "可用"),
                              color: redemptionActive ? phaseColor(m.phase)
                                   : (m.active ? AppPalette.warn : AppPalette.good))) {
            if redemptionActive {
                activeSummary(redemption: true)
            } else {
                VStack(alignment: .leading, spacing: 7) {
                    Text("登录后进入购买页等待，按配置时间开始查询；无额度时在同页重试，有额度才进入购买。")
                        .font(.system(size: 11)).foregroundStyle(AppPalette.muted)
                        .fixedSize(horizontal: false, vertical: true)
                    feature("clock", "00:15 / 09:00 / 09:15 / 10:15 / 11:15，支持自定义")
                    feature("arrow.triangle.2.circlepath", "同一购买页等待与查询")
                    feature("checkmark.shield", "有额度才提交，只提交一次")
                    if !m.task.isEmpty && taskMode == "redemption" {
                        Text("上次任务已结束 · \(phaseName(m.phase))")
                            .font(.system(size: 10)).foregroundStyle(AppPalette.muted)
                    }
                }
            }
        } actions: {
            if redemptionActive {
                Button("刷新") { Task { await m.refresh() } }.disabled(m.busy)
                Button("取消布防") { confirmDisarm = true }
                    .disabled(m.busy || m.phase == "firing")
            } else {
                Button("新建布防") { armMode = .redemption; showArm = true }
                    .buttonStyle(CardButtonStyle(primary: true))
                    .disabled(m.active)
                Button("查看历史") { tab = 3 }
            }
        }
    }

    private func activeSummary(redemption: Bool) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Text("\(stringValue(m.task["code"]) ?? "—") · \(stringValue(m.task["amount"]) ?? "—") 元")
                .font(.system(size: 17, weight: .semibold, design: .rounded))
            if redemption {
                Text("窗口 \(shortTime(m.task["at"])) 起 \(stringValue(m.task["window_minutes"]) ?? "3") 分钟")
                    .font(.system(size: 11)).foregroundStyle(AppPalette.muted)
            } else {
                Text("开售 \(shortTime(m.task["at"]))")
                    .font(.system(size: 11)).foregroundStyle(AppPalette.muted)
            }
            HStack(spacing: 12) {
                Metric("最近心跳", ageText(m.status["last_tick_age_s"]))
                Metric("图案输入", "\(stringValue(m.task["patterns_sent"]) ?? "0") 次")
            }
            if m.phase == "waiting" {
                Text("同一购买页等待与查询；还没有提交。")
                    .font(.system(size: 10)).foregroundStyle(AppPalette.muted)
            }
            if m.phase == "firing" && !m.running {
                Text("提交中进程已退出：先查交易记录，不要补单或重试。")
                    .font(.system(size: 10)).foregroundStyle(AppPalette.accent)
            }
        }
    }

    private func placeholder(icon: String, title: String, text: String,
                             features: [String], tint: Color) -> some View {
        ModeCard(icon: icon, tint: tint, title: title, subtitle: "正在开发",
                 badge: Badge(text: "正在做", color: AppPalette.warn)) {
            VStack(alignment: .leading, spacing: 7) {
                Text(text)
                    .font(.system(size: 11)).foregroundStyle(AppPalette.muted)
                    .fixedSize(horizontal: false, vertical: true)
                ForEach(features, id: \.self) { feature("hammer", $0) }
            }
        } actions: {
            Button("敬请期待") {}.disabled(true)
        }
    }

    private func feature(_ icon: String, _ text: String) -> some View {
        HStack(spacing: 7) {
            Image(systemName: icon).font(.system(size: 10)).foregroundStyle(AppPalette.muted).frame(width: 13)
            Text(text).font(.system(size: 11)).foregroundStyle(AppPalette.muted)
        }
    }
}

struct ModeCard<Content: View, Actions: View>: View {
    let icon: String
    let tint: Color
    let title: String
    let subtitle: String
    let badge: Badge?
    let content: Content
    let actions: Actions

    init(icon: String, tint: Color, title: String, subtitle: String, badge: Badge? = nil,
         @ViewBuilder content: () -> Content, @ViewBuilder actions: () -> Actions) {
        self.icon = icon
        self.tint = tint
        self.title = title
        self.subtitle = subtitle
        self.badge = badge
        self.content = content()
        self.actions = actions()
    }

    var body: some View {
        HStack(alignment: .center, spacing: 18) {
            IconTile(icon: icon, tint: tint)
            VStack(alignment: .leading, spacing: 7) {
                Text(title).font(.system(size: 17, weight: .semibold))
                Text(subtitle).font(.system(size: 11)).foregroundStyle(AppPalette.muted)
                content
            }
            Spacer(minLength: 12)
            VStack(alignment: .trailing, spacing: 9) {
                if let badge { badge }
                actions
            }
        }
        .padding(20)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .background(AppPalette.card, in: RoundedRectangle(cornerRadius: 14))
    }
}
