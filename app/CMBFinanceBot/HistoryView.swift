import SwiftUI
import AppKit

struct HistoryView: View {
    @EnvironmentObject var m: Model
    @State private var selected = 0
    @State private var showLog = false

    var body: some View {
        VStack(spacing: 14) {
            summary
            HStack(spacing: 14) {
                listCard
                detailCard
            }
            .frame(maxHeight: .infinity)
        }
        .padding(.horizontal, 26)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .sheet(isPresented: $showLog) { logSheet }
        .onChange(of: m.history.count) { _ in
            if selected >= m.history.count { selected = 0 }
        }
    }

    private var summary: some View {
        HStack(spacing: 10) {
            stat("总记录", "\(m.historyTotal)")
            stat("已完成", "\(count("done"))", color: AppPalette.good)
            stat("已中止", "\(count("aborted"))", color: AppPalette.warn)
            stat("已取消", "\(count("disarmed"))", color: AppPalette.muted)
            stat("演练", "\(dryRuns)", color: AppPalette.muted)
        }
    }

    private var listCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("历史任务").font(.system(size: 13, weight: .semibold))
                Spacer()
                Text("\(m.history.count) / \(m.historyTotal)")
                    .font(.system(size: 10)).foregroundStyle(AppPalette.muted)
                Button("刷新") { Task { await m.loadHistory() } }.disabled(m.busy)
            }
            if m.history.isEmpty {
                VStack(spacing: 8) {
                    Image(systemName: "clock.arrow.circlepath").font(.system(size: 22)).foregroundStyle(AppPalette.muted)
                    Text("暂无历史任务").font(.system(size: 12, weight: .medium))
                    Text("完成一次值守后会自动写入 var/night/history.jsonl。")
                        .font(.system(size: 10)).foregroundStyle(AppPalette.muted)
                        .multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView {
                    LazyVStack(spacing: 5) {
                        ForEach(Array(m.history.enumerated()), id: \.offset) { index, record in
                            Button { selected = index } label: {
                                row(record, isSelected: index == selected)
                            }
                            .buttonStyle(.plain)
                            .pointingHand()
                        }
                    }
                }
            }
        }
        .padding(16)
        .frame(width: 330)
        .frame(maxHeight: .infinity, alignment: .top)
        .background(AppPalette.card, in: RoundedRectangle(cornerRadius: 14))
    }

    private var detailCard: some View {
        Group {
            if selected < m.history.count {
                detail(m.history[selected])
            } else {
                VStack(spacing: 10) {
                    Image(systemName: "sidebar.left").font(.system(size: 22)).foregroundStyle(AppPalette.muted)
                    Text("选择左侧记录查看详情").font(.system(size: 12)).foregroundStyle(AppPalette.muted)
                    Button("查看值守日志") { showLog = true }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(AppPalette.card, in: RoundedRectangle(cornerRadius: 14))
    }

    private func detail(_ record: [String: Any]) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text(stringValue(record["code"]) ?? "—")
                        .font(.system(size: 20, weight: .semibold, design: .rounded))
                    Text("\(stringValue(record["amount"]) ?? "—") 元")
                        .font(.system(size: 14, weight: .medium)).foregroundStyle(AppPalette.muted)
                    Spacer()
                    Badge(text: phaseName(stringValue(record["phase"]) ?? ""),
                          color: phaseColor(stringValue(record["phase"]) ?? ""))
                    if boolValue(record["dry_run"]) == true { Badge(text: "演练") }
                }
                LazyVGrid(columns: [GridItem(.flexible(), spacing: 14),
                                    GridItem(.flexible(), spacing: 14),
                                    GridItem(.flexible(), spacing: 14)], alignment: .leading, spacing: 12) {
                    Detail("开售时间", shortTime(record["at"]))
                    Detail("布防时间", shortTime(record["armed_at"]))
                    Detail("结束时间", shortTime(record["ended_at"]))
                    Detail("提交时间", shortTime(record["fired_at"]))
                    Detail("阶段", phaseName(stringValue(record["phase"]) ?? ""))
                    Detail("结果", stringValue(record["result"]) ?? "未记录")
                }
                if !arrayValue(record["resumes"]).isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("恢复记录").font(.system(size: 11)).foregroundStyle(AppPalette.muted)
                        ForEach(Array(arrayValue(record["resumes"]).enumerated()), id: \.offset) { _, resume in
                            Text("\(shortTime(resume["at"])) · \(stringValue(resume["by"]) ?? "—") · \(stringValue(resume["reason"]) ?? "—")")
                                .font(.system(size: 11)).textSelection(.enabled)
                        }
                    }
                }
                Divider().overlay(Color.white.opacity(0.05))
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text("值守日志").font(.system(size: 12, weight: .semibold))
                        Spacer()
                        Button("刷新日志") { Task { await m.loadLog() } }.disabled(m.busy)
                        Button("查看全部") { showLog = true }
                    }
                    LogText(lines: Array(m.logLines.suffix(200)))
                        .frame(height: 210)
                        .padding(10)
                        .background(AppPalette.input, in: RoundedRectangle(cornerRadius: 8))
                    HStack {
                        Button("复制日志") { copyText(m.logLines.joined(separator: "\n")) }
                            .disabled(m.logLines.isEmpty)
                        Button("打开文件") {
                            guard !m.logPath.isEmpty else { return }
                            NSWorkspace.shared.open(URL(fileURLWithPath: m.logPath))
                        }.disabled(m.logPath.isEmpty)
                        Spacer()
                        Text("全局 watch.log，不按任务拆分")
                            .font(.system(size: 10)).foregroundStyle(AppPalette.muted)
                    }
                }
            }
        }
    }

    private var logSheet: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("值守日志").font(.system(size: 17, weight: .semibold))
                Spacer()
                Button("复制") { copyText(m.logLines.joined(separator: "\n")) }
                Button("打开文件") {
                    guard !m.logPath.isEmpty else { return }
                    NSWorkspace.shared.open(URL(fileURLWithPath: m.logPath))
                }.disabled(m.logPath.isEmpty)
                Button("关闭") { showLog = false }
            }
            LogText(lines: m.logLines).frame(maxWidth: .infinity, maxHeight: .infinity)
            Text("日志为全局 watch.log，不按任务拆分。").font(.system(size: 10)).foregroundStyle(AppPalette.muted)
        }
        .padding(24).frame(width: 860, height: 580)
        .background(AppPalette.background).buttonStyle(CardButtonStyle()).preferredColorScheme(.dark)
    }

    private func row(_ record: [String: Any], isSelected: Bool) -> some View {
        let phase = stringValue(record["phase"]) ?? ""
        return HStack(spacing: 9) {
            Circle().fill(phaseColor(phase)).frame(width: 7, height: 7)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 5) {
                    Text(stringValue(record["code"]) ?? "—")
                        .font(.system(size: 12, weight: .medium))
                    if boolValue(record["dry_run"]) == true {
                        Badge(text: "演练")
                    }
                }
                Text("\(stringValue(record["amount"]) ?? "—") 元 · \(shortTime(record["at"]))")
                    .font(.system(size: 10)).foregroundStyle(AppPalette.muted)
            }
            Spacer(minLength: 4)
            VStack(alignment: .trailing, spacing: 3) {
                Text(phaseName(phase)).font(.system(size: 10, weight: .medium)).foregroundStyle(phaseColor(phase))
                Text(shortTime(record["ended_at"])).font(.system(size: 9)).foregroundStyle(AppPalette.muted)
            }
        }
        .padding(9)
        .background(isSelected ? AppPalette.button.opacity(0.55) : Color.clear,
                    in: RoundedRectangle(cornerRadius: 8))
        .contentShape(RoundedRectangle(cornerRadius: 8))
    }

    private func stat(_ title: String, _ value: String, color: Color = Color(white: 0.92)) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.system(size: 10)).foregroundStyle(AppPalette.muted)
            Text(value).font(.system(size: 17, weight: .semibold, design: .rounded)).foregroundStyle(color)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 12).padding(.vertical, 9)
        .background(AppPalette.card, in: RoundedRectangle(cornerRadius: 10))
    }

    private func count(_ phase: String) -> Int {
        m.history.filter { stringValue($0["phase"]) == phase }.count
    }

    private var dryRuns: Int {
        m.history.filter { boolValue($0["dry_run"]) == true }.count
    }
}
