import SwiftUI

struct TasksView: View {
    @EnvironmentObject var m: Model
    @Binding var tab: Int
    @State private var showArm = false
    @State private var confirmDisarm = false

    var body: some View {
        GeometryReader { geo in
            let spacing: CGFloat = 14
            let height = max(150, (geo.size.height - spacing * 2) / 3)
            VStack(spacing: spacing) {
                firstLaunch.frame(height: height)
                placeholder(icon: "arrow.triangle.2.circlepath",
                            title: "捡漏模式",
                            text: "白天轮询多只理财，有人撤单、额度重新放出时自动买入。",
                            features: ["反复查看多只理财", "按可购额度比例买入", "白天运行，可设终止时间"],
                            tint: Color(red: 0.35, green: 0.62, blue: 0.95))
                    .frame(height: height)
                placeholder(icon: "clock.arrow.circlepath",
                            title: "赎回抢购模式",
                            text: "00:15 盯住一只理财，等赎回额度放出后立即买入。",
                            features: ["00:15 开始盯盘", "按可购额度比例买入", "默认运行 3 分钟"],
                            tint: Color(red: 0.72, green: 0.45, blue: 0.95))
                    .frame(height: height)
            }
            .padding(.horizontal, 26)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        }
        .sheet(isPresented: $showArm) { ArmSheet().environmentObject(m) }
        .alert("取消当前布防？", isPresented: $confirmDisarm) {
            Button("继续值守", role: .cancel) {}
            Button("确认取消", role: .destructive) {
                Task { await m.action(["disarm"], label: "取消布防") }
            }
        } message: {
            Text("取消后本轮不会再提交；已经发生的交易仍要查交易记录。")
        }
    }

    private var firstLaunch: some View {
        ModeCard(icon: "bolt.fill", tint: AppPalette.accent, title: "首发模式",
                 subtitle: "开售准点抢一只新发理财",
                 badge: Badge(text: "可用", color: AppPalette.good)) {
            if m.active && !m.task.isEmpty {
                activeSummary
            } else {
                VStack(alignment: .leading, spacing: 7) {
                    Text("开售前自动冷启动并登录，开售后 200ms 直达购买页，只提交一次。")
                        .font(.system(size: 11)).foregroundStyle(AppPalette.muted)
                        .fixedSize(horizontal: false, vertical: true)
                    feature("clock", "开售前 15 分钟冷启动并登录")
                    feature("bolt.fill", "开售 +200ms 打开购买页")
                    feature("checkmark.shield", "只提交一次，失败不重试")
                    if !m.task.isEmpty {
                        Text("上次任务已结束 · \(phaseName(m.phase))")
                            .font(.system(size: 10)).foregroundStyle(AppPalette.muted)
                    }
                }
            }
        } actions: {
            if m.active && !m.task.isEmpty {
                Button("刷新") { Task { await m.refresh() } }.disabled(m.busy)
                Button("取消布防") { confirmDisarm = true }
                    .disabled(m.busy || m.phase == "firing")
            } else {
                Button("新建布防") { showArm = true }
                    .buttonStyle(CardButtonStyle(primary: true))
                Button("查看历史") { tab = 3 }
            }
        }
    }

    private var activeSummary: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text("\(stringValue(m.task["code"]) ?? "—") · \(stringValue(m.task["amount"]) ?? "—") 元")
                .font(.system(size: 17, weight: .semibold, design: .rounded))
            Text("开售 \(shortTime(m.task["at"]))")
                .font(.system(size: 11)).foregroundStyle(AppPalette.muted)
            HStack(spacing: 12) {
                Metric("最近心跳", ageText(m.status["last_tick_age_s"]))
                Metric("图案输入", "\(stringValue(m.task["patterns_sent"]) ?? "0") 次")
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
