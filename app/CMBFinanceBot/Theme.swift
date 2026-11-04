import SwiftUI
import AppKit

enum AppPalette {
    static let background = Color(white: 30.0 / 255)
    static let sidebar = Color(white: 35.0 / 255)
    static let card = Color(white: 41.0 / 255)
    static let input = Color(white: 33.0 / 255)
    static let button = Color(white: 55.0 / 255)
    static let muted = Color(white: 0.64)
    static let accent = Color(red: 0.88, green: 0.26, blue: 0.32)
    static let good = Color(red: 0.36, green: 0.76, blue: 0.52)
    static let warn = Color(red: 0.95, green: 0.66, blue: 0.30)
}

struct Card<Content: View>: View {
    let title: String
    let subtitle: String?
    let fillHeight: Bool
    let content: Content
    init(_ title: String, subtitle: String? = nil, fillHeight: Bool = false, @ViewBuilder content: () -> Content) {
        self.title = title
        self.subtitle = subtitle
        self.fillHeight = fillHeight
        self.content = content()
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 5) {
                Text(title).font(.system(size: 14, weight: .semibold))
                if let subtitle { Text(subtitle).font(.system(size: 12)).foregroundStyle(AppPalette.muted) }
            }
            content
        }
        .frame(maxWidth: .infinity, maxHeight: fillHeight ? .infinity : nil, alignment: .topLeading)
        .padding(18)
        .background(AppPalette.card, in: RoundedRectangle(cornerRadius: 14))
    }
}

private struct ErrorToast: ViewModifier {
    @EnvironmentObject var m: Model
    let topInset: CGFloat

    func body(content: Content) -> some View {
        content.overlay(alignment: .topTrailing) {
            if let message = m.message {
                VStack(alignment: .leading, spacing: 10) {
                    HStack(spacing: 8) {
                        Image(systemName: "exclamationmark.circle.fill").foregroundStyle(AppPalette.accent)
                        Text("操作提示").font(.system(size: 12, weight: .semibold))
                        Spacer(minLength: 8)
                        Button { copyText(message) } label: { Image(systemName: "doc.on.doc") }
                            .help("复制完整提示").accessibilityLabel("复制完整提示")
                        Button { m.message = nil } label: { Image(systemName: "xmark") }
                            .help("关闭提示").accessibilityLabel("关闭提示")
                    }
                    .buttonStyle(.plain)
                    ViewThatFits(in: .vertical) {
                        messageText(message)
                        ScrollView { messageText(message) }.frame(height: 140)
                    }
                    .frame(maxHeight: 140, alignment: .topLeading)
                }
                .padding(16)
                .frame(maxWidth: 400, alignment: .leading)
                .background(AppPalette.button, in: RoundedRectangle(cornerRadius: 12))
                .shadow(color: .black.opacity(0.3), radius: 12, y: 5)
                .padding(.horizontal, 20).padding(.top, topInset)
            }
        }
    }

    private func messageText(_ message: String) -> some View {
        Text(message).font(.system(size: 12)).foregroundStyle(Color(white: 0.94))
            .textSelection(.enabled)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

extension View {
    func errorToast(topInset: CGFloat = 20) -> some View {
        modifier(ErrorToast(topInset: topInset))
    }
}

struct DashboardCard<Content: View, Footer: View>: View {
    let title: String
    let icon: String
    let content: Content
    let footer: Footer
    init(_ title: String, icon: String, @ViewBuilder content: () -> Content,
         @ViewBuilder footer: () -> Footer) {
        self.title = title
        self.icon = icon
        self.content = content()
        self.footer = footer()
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(spacing: 8) {
                Image(systemName: icon).font(.system(size: 11, weight: .semibold)).foregroundStyle(AppPalette.muted)
                Text(title).font(.system(size: 13, weight: .semibold))
                Spacer(minLength: 0)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 9) {
                    content
                }
                .frame(maxWidth: .infinity, alignment: .topLeading)
            }
            footer.fixedSize(horizontal: false, vertical: true)
        }
        .padding(12)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(AppPalette.card, in: RoundedRectangle(cornerRadius: 14))
    }
}

struct IconTile: View {
    let icon: String
    let tint: Color
    var body: some View {
        Image(systemName: icon)
            .font(.system(size: 18, weight: .semibold))
            .foregroundStyle(tint)
            .frame(width: 40, height: 40)
            .background(tint.opacity(0.15), in: RoundedRectangle(cornerRadius: 10))
    }
}

struct Badge: View {
    let text: String
    var color: Color = AppPalette.muted
    var body: some View {
        Text(text)
            .font(.system(size: 10, weight: .semibold))
            .padding(.horizontal, 8).padding(.vertical, 3)
            .foregroundStyle(color)
            .background(color.opacity(0.15), in: Capsule())
    }
}

struct Metric: View {
    let title: String
    let value: String
    var color: Color?
    init(_ title: String, _ value: String, color: Color? = nil) {
        self.title = title
        self.value = value
        self.color = color
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.system(size: 10)).foregroundStyle(AppPalette.muted).lineLimit(1)
            Text(value).font(.system(size: 12, weight: .medium))
                .foregroundStyle(color ?? Color(white: 0.92))
                .lineLimit(1).minimumScaleFactor(0.75)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct MetricGrid<Content: View>: View {
    let content: Content
    init(@ViewBuilder content: () -> Content) { self.content = content() }
    var body: some View {
        LazyVGrid(columns: [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)],
                  alignment: .leading, spacing: 8) { content }
    }
}

struct Detail: View {
    let title: String
    let value: String
    init(_ title: String, _ value: Any?) {
        self.title = title
        self.value = stringValue(value) ?? "—"
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title).font(.system(size: 11)).foregroundStyle(AppPalette.muted)
            Text(value).font(.system(size: 13, weight: .medium)).textSelection(.enabled)
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct StatusDot: View {
    let state: Bool?
    var body: some View {
        Circle().fill(color).frame(width: 6, height: 6)
    }
    private var color: Color {
        if let state { return state ? AppPalette.good : AppPalette.warn }
        return AppPalette.muted
    }
}

struct EqualHeightColumns: Layout {
    var spacing: CGFloat = 16
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? 700
        let column = max(0, (width - spacing * CGFloat(max(0, subviews.count - 1))) / CGFloat(max(1, subviews.count)))
        let height = subviews.map { $0.sizeThatFits(ProposedViewSize(width: column, height: nil)).height }.max() ?? 0
        return CGSize(width: width, height: height)
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let width = max(0, (bounds.width - spacing * CGFloat(max(0, subviews.count - 1))) / CGFloat(max(1, subviews.count)))
        for (index, view) in subviews.enumerated() {
            view.place(at: CGPoint(x: bounds.minX + CGFloat(index) * (width + spacing), y: bounds.minY),
                       anchor: .topLeading, proposal: ProposedViewSize(width: width, height: bounds.height))
        }
    }
}

struct CardButtonStyle: ButtonStyle {
    var primary = false
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.system(size: 12, weight: .medium))
            .lineLimit(1).fixedSize(horizontal: true, vertical: false)
            .padding(.horizontal, 14).padding(.vertical, 9)
            .foregroundStyle(Color.white.opacity(enabled ? 0.94 : 0.32))
            .background((primary ? AppPalette.accent : AppPalette.button)
                .opacity(enabled ? (configuration.isPressed ? 0.7 : 1) : 0.5), in: RoundedRectangle(cornerRadius: 8))
            .contentShape(RoundedRectangle(cornerRadius: 8))
            .pointingHand(enabled)
    }
}


struct CompactButtonStyle: ButtonStyle {
    var primary = false
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.system(size: 11, weight: .medium))
            .lineLimit(1).fixedSize(horizontal: true, vertical: false)
            .padding(.horizontal, 8).padding(.vertical, 6)
            .foregroundStyle(Color.white.opacity(enabled ? 0.94 : 0.32))
            .background((primary ? AppPalette.accent : AppPalette.button)
                .opacity(enabled ? (configuration.isPressed ? 0.7 : 1) : 0.5), in: RoundedRectangle(cornerRadius: 7))
            .contentShape(RoundedRectangle(cornerRadius: 7))
            .pointingHand(enabled)
    }
}

struct PointingHand: ViewModifier {
    var active = true
    @State private var hovering = false
    func body(content: Content) -> some View {
        content
            .onHover { inside in
                guard active, inside != hovering else { return }
                hovering = inside
                if inside { NSCursor.pointingHand.push() } else { NSCursor.pop() }
            }
            .onChange(of: active) { enabled in
                guard !enabled, hovering else { return }
                hovering = false
                NSCursor.pop()
            }
            .onDisappear {
                guard hovering else { return }
                hovering = false
                NSCursor.pop()
            }
    }
}

extension View {
    func cardField() -> some View {
        self.textFieldStyle(.plain).font(.system(size: 13))
            .padding(.horizontal, 12).padding(.vertical, 11)
            .background(AppPalette.input, in: RoundedRectangle(cornerRadius: 8))
    }
    func pointingHand(_ active: Bool = true) -> some View {
        modifier(PointingHand(active: active))
    }
}

struct WindowDragRegion: NSViewRepresentable {
    final class DragView: NSView {
        override var mouseDownCanMoveWindow: Bool { true }
        override func mouseDown(with event: NSEvent) { window?.performDrag(with: event) }
    }
    func makeNSView(context: Context) -> DragView { DragView() }
    func updateNSView(_ nsView: DragView, context: Context) {}
}

struct LogText: View {
    let lines: [String]
    var body: some View {
        ScrollView([.vertical, .horizontal]) {
            Text(lines.isEmpty ? "暂无日志" : lines.joined(separator: "\n"))
                .font(.system(size: 10, design: .monospaced))
                .lineSpacing(3)
                .foregroundStyle(Color(white: 0.72))
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

func phaseName(_ phase: String) -> String {
    ["armed": "已布防", "preparing": "准备中", "waiting": "盯盘中", "firing": "正在提交",
     "done": "已完成", "aborted": "已中止", "disarmed": "已取消"][phase] ?? phase
}

func phaseColor(_ phase: String) -> Color {
    switch phase {
    case "armed": return AppPalette.accent
    case "preparing": return AppPalette.warn
    case "waiting": return AppPalette.accent
    case "firing": return AppPalette.accent
    case "done": return AppPalette.good
    case "aborted": return AppPalette.warn
    case "disarmed": return AppPalette.muted
    default: return AppPalette.muted
    }
}

func shortTime(_ value: Any?) -> String {
    guard let text = stringValue(value) else { return "—" }
    return text.replacingOccurrences(of: "T", with: " ").components(separatedBy: ".")[0]
}

func ageText(_ value: Any?) -> String {
    let seconds: Double?
    if let number = value as? NSNumber { seconds = number.doubleValue }
    else if let value = value as? Double { seconds = value }
    else { seconds = nil }
    guard let seconds, seconds >= 0 else { return "—" }
    if seconds < 60 { return "\(Int(seconds)) 秒前" }
    if seconds < 3600 { return "\(Int(seconds / 60)) 分钟前" }
    return "\(Int(seconds / 3600)) 小时前"
}

func stringValue(_ value: Any?) -> String? {
    if let value = value as? String { return value }
    if let value = value as? NSNumber { return value.stringValue }
    return nil
}

func boolValue(_ value: Any?) -> Bool? {
    if let value = value as? Bool { return value }
    if let value = value as? NSNumber { return value.boolValue }
    return nil
}

func dictValue(_ value: Any?) -> [String: Any] {
    value as? [String: Any] ?? [:]
}

func arrayValue(_ value: Any?) -> [[String: Any]] {
    value as? [[String: Any]] ?? []
}

func copyText(_ text: String) {
    NSPasteboard.general.clearContents()
    NSPasteboard.general.setString(text, forType: .string)
}

func validCode(_ text: String) -> Bool {
    text.range(of: "^[A-Za-z0-9]{4,20}$", options: .regularExpression) != nil
}

func validAmount(_ text: String) -> Bool {
    guard text.range(of: "^[0-9]+(\\.[0-9]{1,2})?$", options: .regularExpression) != nil,
          let value = Double(text), value > 0, value <= 50_000 else { return false }
    return true
}
