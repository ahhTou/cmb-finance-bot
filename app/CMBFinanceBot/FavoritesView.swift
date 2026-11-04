import SwiftUI

/// Saved product codes (code + title), editable in place.
struct FavoritesView: View {
    @EnvironmentObject var m: Model
    @State private var code = ""
    @State private var title = ""
    @State private var drafts: [String: String] = [:]
    @State private var removing: String?

    private var canAdd: Bool {
        validCode(code.trimmingCharacters(in: .whitespaces))
            && !title.trimmingCharacters(in: .whitespaces).isEmpty
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Card("添加收藏", subtitle: "只保存产品代码和标题，不保存金额、时间或凭据。") {
                HStack(alignment: .top, spacing: 12) {
                    labeled("产品代码") {
                        TextField("如 JX040229", text: $code).cardField()
                    }
                    labeled("标题") {
                        TextField("如 招睿丰和 30 天", text: $title).cardField()
                    }
                    Button("添加") { add() }
                        .buttonStyle(CardButtonStyle(primary: true))
                        .disabled(!canAdd || m.busy)
                }
            }
            Card("已收藏", subtitle: "布防和单笔演练都能直接选；共 \(m.favorites.count) 项") {
                if m.favorites.isEmpty {
                    Text("还没有收藏。添加后，填产品代码的地方会出现快捷选择。")
                        .font(.system(size: 12)).foregroundStyle(AppPalette.muted)
                } else {
                    VStack(spacing: 0) {
                        ForEach(Array(m.favorites.enumerated()), id: \.offset) { _, row in
                            rowView(row)
                            Divider().overlay(Color.white.opacity(0.06))
                        }
                    }
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 26)
        .task { syncDrafts() }
        .onChange(of: m.favorites.count) { _ in syncDrafts() }
        .alert("删除收藏？", isPresented: Binding(
            get: { removing != nil }, set: { if !$0 { removing = nil } })) {
            Button("取消", role: .cancel) { removing = nil }
            Button("删除", role: .destructive) {
                if let value = removing { remove(value) }
                removing = nil
            }
        } message: {
            Text("只删除本地收藏，不影响银行里的产品。")
        }
    }

    @ViewBuilder
    private func rowView(_ row: [String: Any]) -> some View {
        let value = stringValue(row["code"]) ?? ""
        HStack(spacing: 12) {
            Text(value)
                .font(.system(size: 12, weight: .medium, design: .monospaced))
                .frame(width: 96, alignment: .leading)
            TextField("标题", text: Binding(
                get: { drafts[value] ?? (stringValue(row["title"]) ?? "") },
                set: { drafts[value] = $0 }))
                .cardField()
            Button("保存标题") { save(value) }
                .disabled(m.busy || (drafts[value] ?? "").trimmingCharacters(in: .whitespaces).isEmpty)
            Button("删除") { removing = value }
                .foregroundStyle(AppPalette.accent)
        }
        .padding(.vertical, 7)
    }

    @ViewBuilder
    private func labeled<Content: View>(_ title: String,
                                        @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.caption).foregroundStyle(AppPalette.muted)
            content()
        }
    }

    private func add() {
        let value = code.trimmingCharacters(in: .whitespaces)
        let name = title.trimmingCharacters(in: .whitespaces)
        code = ""
        title = ""
        Task { await m.action(["favorites", "--add", value, "--title", name], label: "添加收藏") }
    }

    private func save(_ value: String) {
        guard let name = drafts[value]?.trimmingCharacters(in: .whitespaces), !name.isEmpty else { return }
        Task { await m.action(["favorites", "--add", value, "--title", name], label: "修改标题") }
    }

    private func remove(_ value: String) {
        Task { await m.action(["favorites", "--remove", value], label: "删除收藏") }
    }

    private func syncDrafts() {
        drafts = m.favorites.reduce(into: [:]) { result, row in
            if let value = stringValue(row["code"]) {
                result[value] = stringValue(row["title"]) ?? ""
            }
        }
    }
}

/// Compact chips that fill a product-code field from saved favorites.
struct FavoritePicker: View {
    @EnvironmentObject var m: Model
    @Binding var code: String

    var body: some View {
        if !m.favorites.isEmpty {
            // Wraps instead of overflowing: chips used to run past the card / over the neighbouring card.
            FlowLayout(spacing: 7) {
                Image(systemName: "star.fill")
                    .font(.system(size: 9))
                    .foregroundStyle(AppPalette.warn.opacity(0.85))
                ForEach(Array(m.favorites.prefix(4).enumerated()), id: \.offset) { _, row in
                    Button(label(row)) { fill(row) }
                        .buttonStyle(CompactButtonStyle())
                }
                if m.favorites.count > 4 {
                    Menu("更多") {
                        ForEach(Array(m.favorites.enumerated()), id: \.offset) { _, row in
                            let value = stringValue(row["code"]) ?? ""
                            Button("\(label(row)) · \(value)") { fill(row) }
                        }
                    }
                    .menuStyle(.borderlessButton)
                    .font(.system(size: 11))
                    .fixedSize()
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func label(_ row: [String: Any]) -> String {
        let value = stringValue(row["code"]) ?? ""
        return stringValue(row["title"]) ?? value
    }

    private func fill(_ row: [String: Any]) {
        if let value = stringValue(row["code"]) { code = value }
    }
}

/// Lays subviews out in a row and wraps to the next line when the width runs out.
struct FlowLayout: Layout {
    var spacing: CGFloat = 7
    var lineSpacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, lineHeight: CGFloat = 0, maxX: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > 0, x + size.width > width {
                x = 0
                y += lineHeight + lineSpacing
                lineHeight = 0
            }
            x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
            maxX = max(maxX, x - spacing)
        }
        return CGSize(width: maxX.isFinite ? maxX : 0, height: y + lineHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, lineHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > bounds.minX, x + size.width > bounds.maxX {
                x = bounds.minX
                y += lineHeight + lineSpacing
                lineHeight = 0
            }
            subview.place(at: CGPoint(x: x, y: y), anchor: .topLeading, proposal: ProposedViewSize(size))
            x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
        }
    }
}
