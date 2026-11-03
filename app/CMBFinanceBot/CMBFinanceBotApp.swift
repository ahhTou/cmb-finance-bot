import SwiftUI
import AppKit

@MainActor final class ManagementWindow: NSWindow {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
    override func performKeyEquivalent(with event: NSEvent) -> Bool {
        if event.modifierFlags.contains(.command), event.charactersIgnoringModifiers == "w" {
            performClose(nil)
            return true
        }
        return super.performKeyEquivalent(with: event)
    }

    @objc func toggleZoom(_ sender: Any?) { zoom(sender) }
}

@MainActor final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private let model = Model()
    private var managementWindow: ManagementWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let view = ManagementView().environmentObject(model)
            .frame(minWidth: 940, minHeight: 680)
        let window = ManagementWindow(contentRect: NSRect(x: 0, y: 0, width: 1040, height: 760),
                                      styleMask: [.titled, .fullSizeContentView, .resizable, .closable, .miniaturizable],
                                      backing: .buffered, defer: false)
        window.title = "招行理财值守"
        window.identifier = NSUserInterfaceItemIdentifier("management")
        window.delegate = self
        window.contentView = NSHostingView(rootView: view)
        window.minSize = NSSize(width: 940, height: 680)
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.titlebarSeparatorStyle = .none
        window.toolbar = nil
        window.backgroundColor = NSColor(calibratedWhite: 30.0 / 255, alpha: 1)
        window.isOpaque = true
        window.isMovableByWindowBackground = true
        window.hasShadow = true
        window.isReleasedWhenClosed = false
        window.setFrameAutosaveName("management")
        if !window.setFrameUsingName("management") { window.center() }
        managementWindow = window
        installMenus()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func installMenus() {
        let main = NSMenu()
        let appItem = NSMenuItem()
        main.addItem(appItem)
        let appMenu = NSMenu(title: "招行理财值守")
        appMenu.addItem(withTitle: "隐藏招行理财值守", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "退出招行理财值守", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q").target = NSApp
        appItem.submenu = appMenu
        let editItem = NSMenuItem()
        main.addItem(editItem)
        let edit = NSMenu(title: "编辑")
        edit.addItem(withTitle: "撤销", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "复制", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        let windowItem = NSMenuItem()
        main.addItem(windowItem)
        let windowMenu = NSMenu(title: "窗口")
        windowMenu.addItem(withTitle: "关闭窗口", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w").target = managementWindow
        windowMenu.addItem(withTitle: "最小化", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "缩放", action: #selector(ManagementWindow.toggleZoom(_:)), keyEquivalent: "")
        windowItem.submenu = windowMenu
        NSApp.mainMenu = main
        NSApp.windowsMenu = windowMenu
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        model.windowVisible = false
        sender.orderOut(nil)
        return false
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        model.windowVisible = true
        managementWindow?.deminiaturize(nil)
        managementWindow?.makeKeyAndOrderFront(nil)
        sender.activate(ignoringOtherApps: true)
        Task { await model.refresh() }
        return false
    }
}

@main struct CMBFinanceBotApp {
    @MainActor static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        withExtendedLifetime(delegate) { app.run() }
    }
}
