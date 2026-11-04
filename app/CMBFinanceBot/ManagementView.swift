import SwiftUI

struct ManagementView: View {
    @EnvironmentObject var m: Model
    @State private var tab = min(max(UserDefaults.standard.integer(forKey: "selectedTab"), 0), 4)
    private let pages = [
        ("任务", "square.stack.3d.up", "三种购买模式"),
        ("状态", "gauge.with.dots.needle.67percent", "运行环境与设备"),
        ("演练", "testtube.2", "测试命令与撤单"),
        ("历史", "clock.arrow.circlepath", "完成情况与日志"),
        ("设置", "gearshape", "项目与凭据")
    ]

    var body: some View {
        ZStack {
            HStack(spacing: 0) {
                sidebar
                VStack(alignment: .leading, spacing: 18) {
                    header
                    ZStack {
                        TasksView(tab: $tab)
                            .opacity(tab == 0 ? 1 : 0).allowsHitTesting(tab == 0).accessibilityHidden(tab != 0)
                        DashboardView(tab: $tab)
                            .opacity(tab == 1 ? 1 : 0).allowsHitTesting(tab == 1).accessibilityHidden(tab != 1)
                        DrillView()
                            .opacity(tab == 2 ? 1 : 0).allowsHitTesting(tab == 2).accessibilityHidden(tab != 2)
                        HistoryView()
                            .opacity(tab == 3 ? 1 : 0).allowsHitTesting(tab == 3).accessibilityHidden(tab != 3)
                        if tab == 4 && m.windowVisible { SettingsView() }
                    }
                    .disabled(m.root.isEmpty && tab != 4)
                    .padding(.bottom, 26)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(AppPalette.background)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity).ignoresSafeArea()
            .background(AppPalette.background)
            .foregroundStyle(Color(white: 0.94)).tint(AppPalette.accent)
            .buttonStyle(CardButtonStyle()).toggleStyle(.switch).preferredColorScheme(.dark)
            .errorToast(topInset: 82)

            if m.active {
                LiveView()
                    .transition(.opacity)
                    .zIndex(20)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity).ignoresSafeArea()
        .background(AppPalette.background)
        .animation(.easeInOut(duration: 0.2), value: m.active)
        .task {
            if m.root.isEmpty { tab = 4 }
            await m.refreshCurrent(tab)
            while !Task.isCancelled {
                let interval: UInt64 = m.windowVisible ? 5_000_000_000 : 30_000_000_000
                try? await Task.sleep(nanoseconds: interval)
                if m.windowVisible { await m.refresh() }
            }
        }
        .onChange(of: tab) { value in
            UserDefaults.standard.set(value, forKey: "selectedTab")
            Task { await m.refreshCurrent(value) }
        }
        .onChange(of: m.windowVisible) { visible in
            if visible { Task { await m.refresh() } }
        }
    }

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 0) {
            WindowDragRegion().frame(height: 32)
            HStack(spacing: 10) {
                Image(nsImage: NSApp.applicationIconImage).resizable().frame(width: 34, height: 34)
                VStack(alignment: .leading, spacing: 4) {
                    Text("招行理财值守").font(.system(size: 13, weight: .semibold))
                    Text("本机管理").font(.system(size: 11)).foregroundStyle(AppPalette.muted)
                }
            }
            .padding(.top, 25).padding(.bottom, 32)
            .background(WindowDragRegion())
            VStack(spacing: 7) {
                ForEach(0..<pages.count, id: \.self) { sidebarItem($0) }
            }
            HStack(spacing: 7) {
                Circle().fill(m.active ? AppPalette.accent : AppPalette.muted).frame(width: 5, height: 5)
                Text(phaseName(m.phase)).font(.system(size: 11)).foregroundStyle(AppPalette.muted)
            }
            .padding(.horizontal, 12).padding(.top, 20)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 16).padding(.top, 12).padding(.bottom, 16)
        .frame(width: 196).frame(maxHeight: .infinity)
        .background(AppPalette.sidebar)
    }

    private var header: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 6) {
                Text(pages[tab].0).font(.system(size: 23, weight: .semibold))
                Text(m.lastRefresh == nil ? pages[tab].2 : "\(pages[tab].2) · 上次刷新 \(m.lastRefreshText)")
                    .font(.system(size: 12)).foregroundStyle(AppPalette.muted)
            }
            Spacer()
            if m.busy {
                HStack(spacing: 7) {
                    ProgressView().controlSize(.small)
                    Text(m.busyLabel).font(.system(size: 11)).foregroundStyle(AppPalette.muted)
                }
            }
            Button { Task { await m.refreshCurrent(tab) } } label: {
                Label("刷新", systemImage: "arrow.clockwise")
            }.disabled(m.busy || m.root.isEmpty)
        }
        .frame(height: 54).padding(.horizontal, 26).padding(.top, 20)
        .background(WindowDragRegion())
    }

    private func sidebarItem(_ index: Int) -> some View {
        Button { tab = index } label: {
            HStack(spacing: 11) {
                Image(systemName: pages[index].1).font(.system(size: 14)).frame(width: 20)
                Text(pages[index].0).font(.system(size: 13, weight: tab == index ? .semibold : .regular))
                Spacer()
            }
            .foregroundStyle(tab == index ? Color.white : AppPalette.muted)
            .padding(.horizontal, 12).padding(.vertical, 12)
            .background(tab == index ? AppPalette.button : Color.clear, in: RoundedRectangle(cornerRadius: 9))
            .contentShape(RoundedRectangle(cornerRadius: 9))
        }.buttonStyle(.plain).pointingHand()
    }
}
