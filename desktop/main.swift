import AppKit
import UniformTypeIdentifiers
import WebKit

final class DesktopApp: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler, NSToolbarDelegate {
    private let sidebarPreferenceKey = "sidebarPreference"
    private let themePreferenceKey = "themePreference"
    private let sidebarItem = NSToolbarItem.Identifier("researchSidebar")
    private let themeItem = NSToolbarItem.Identifier("researchTheme")
    private var window: NSWindow!
    private var webView: WKWebView!
    private var backend: Process?
    private var readyPipe: Pipe?
    private var localURL: URL?
    private var readyOutput = Data()

    func applicationDidFinishLaunching(_ notification: Notification) {
        if let iconURL = Bundle.main.url(forResource: "LuLu", withExtension: "icns"),
           let icon = NSImage(contentsOf: iconURL) {
            NSApp.applicationIconImage = icon
        }
        installMenu()
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1080, height: 760),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.title = "LuLu Research"
        window.titlebarAppearsTransparent = true
        window.titlebarSeparatorStyle = .none
        window.toolbarStyle = .unifiedCompact
        let toolbar = NSToolbar(identifier: "researchToolbar")
        toolbar.delegate = self
        window.toolbar = toolbar
        window.minSize = NSSize(width: 560, height: 420)
        let configuration = WKWebViewConfiguration()
        let controller = configuration.userContentController
        controller.add(self, name: sidebarPreferenceKey)
        controller.add(self, name: themePreferenceKey)
        var settings = "document.documentElement.dataset.desktop = 'true';"
        if let preference = UserDefaults.standard.string(forKey: sidebarPreferenceKey),
           preference == "shown" || preference == "hidden" {
            settings += "window.desktopSidebarPreference = '\(preference)';"
        }
        if let theme = UserDefaults.standard.string(forKey: themePreferenceKey),
           theme == "light" || theme == "dark" {
            applyTheme(theme)
            settings += "window.desktopThemePreference = '\(theme)';"
        }
        controller.addUserScript(WKUserScript(source: settings, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        let content = NSView()
        window.contentView = content
        webView.translatesAutoresizingMaskIntoConstraints = false
        content.addSubview(webView)
        let topAnchor = (window.contentLayoutGuide as? NSLayoutGuide)?.topAnchor ?? content.safeAreaLayoutGuide.topAnchor
        NSLayoutConstraint.activate([
            webView.topAnchor.constraint(equalTo: topAnchor),
            webView.bottomAnchor.constraint(equalTo: content.bottomAnchor),
            webView.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: content.trailingAnchor),
        ])
        if UserDefaults.standard.string(forKey: themePreferenceKey) == nil {
            updateWindowColor(dark: window.effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua)
        }
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        showMessage("正在启动本地研究服务…")
        startBackend()
    }

    func toolbarDefaultItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] {
        [sidebarItem, .flexibleSpace, themeItem]
    }

    func toolbarAllowedItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] {
        toolbarDefaultItemIdentifiers(toolbar)
    }

    func toolbar(_ toolbar: NSToolbar, itemForItemIdentifier id: NSToolbarItem.Identifier,
                 willBeInsertedIntoToolbar flag: Bool) -> NSToolbarItem? {
        guard id == sidebarItem || id == themeItem else { return nil }
        let isSidebar = id == sidebarItem
        let item = NSToolbarItem(itemIdentifier: id)
        item.label = isSidebar ? "研究侧栏" : "切换浅色／深色"
        item.toolTip = item.label
        item.image = NSImage(systemSymbolName: isSidebar ? "sidebar.left" : "circle.lefthalf.filled",
                             accessibilityDescription: item.label)
        item.isNavigational = isSidebar
        item.target = self
        item.action = isSidebar ? #selector(toggleSidebar) : #selector(toggleTheme)
        return item
    }

    @objc private func toggleSidebar() {
        webView.evaluateJavaScript("document.querySelector('#sidebar-toggle')?.click()")
    }

    @objc private func toggleTheme() {
        webView.evaluateJavaScript("document.querySelector('#theme-toggle')?.click()")
    }

    private func updateWindowColor(dark: Bool) {
        // Match the web canvas behind the transparent native toolbar.
        window.backgroundColor = dark
            ? NSColor(srgbRed: 37.0 / 255, green: 38.0 / 255, blue: 38.0 / 255, alpha: 1)
            : NSColor(srgbRed: 247.0 / 255, green: 244.0 / 255, blue: 237.0 / 255, alpha: 1)
    }

    private func applyTheme(_ theme: String) {
        let dark = theme == "dark"
        window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        updateWindowColor(dark: dark)
    }

    private func installMenu() {
        let menu = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Quit LuLu Research", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        menu.addItem(appItem)

        let editItem = NSMenuItem()
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = editMenu
        menu.addItem(editItem)
        NSApp.mainMenu = menu
    }

    private func showMessage(_ message: String) {
        webView.loadHTMLString(
            """
            <!doctype html><meta charset="utf-8">
            <style>body{font:16px -apple-system;padding:40px;background:Canvas;color:CanvasText}</style>
            <h1>LuLu Research</h1><p>\(message)</p>
            """,
            baseURL: nil
        )
    }

    private func startBackend() {
        let root = Bundle.main.bundleURL.deletingLastPathComponent()
        let python = root.appendingPathComponent(".venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else {
            showMessage("找不到项目的 Python 环境。请把应用放在仓库根目录，并按 README 安装依赖。")
            return
        }

        let process = Process()
        let pipe = Pipe()
        process.executableURL = python
        process.currentDirectoryURL = root
        process.arguments = ["-m", "research_agent.web_server", "--port", "0", "--desktop"]
        process.standardOutput = pipe
        process.terminationHandler = { [weak self] process in
            DispatchQueue.main.async {
                guard let self, self.backend === process else { return }
                self.stopBackend()
                self.showMessage("本地研究服务已退出。请检查 README 中的依赖安装步骤后重新打开应用。")
            }
        }

        backend = process
        readyPipe = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty {
                handle.readabilityHandler = nil
                return
            }
            DispatchQueue.main.async { self?.readReadyMessage(data) }
        }
        do {
            try process.run()
            try? pipe.fileHandleForWriting.close()
        } catch {
            stopBackend()
            showMessage("无法启动本地研究服务。请检查项目的 Python 环境。")
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 20) { [weak self] in
            guard let self, self.backend != nil, self.localURL == nil else { return }
            self.stopBackend()
            self.showMessage("本地研究服务启动超时。请检查依赖后重新打开应用。")
        }
    }

    private func readReadyMessage(_ bytes: Data) {
        guard backend != nil, localURL == nil else { return }
        readyOutput.append(bytes)
        while let end = readyOutput.firstIndex(of: 10) {
            let line = String(decoding: readyOutput[..<end], as: UTF8.self)
            readyOutput.removeSubrange(...end)
            guard let port = Int(line.trimmingCharacters(in: .whitespacesAndNewlines)), (1...65535).contains(port),
                  let url = URL(string: "http://127.0.0.1:\(port)/") else { continue }
            readyPipe?.fileHandleForReading.readabilityHandler = nil
            localURL = url
            webView.load(URLRequest(url: url))
            return
        }
    }

    private func stopBackend() {
        readyPipe?.fileHandleForReading.readabilityHandler = nil
        if let backend {
            let pid = backend.processIdentifier
            // The desktop server and its MLX subprocesses use a dedicated process group.
            if pid > 0 && kill(-pid, SIGTERM) != 0 && backend.isRunning {
                backend.terminate()
            }
        }
        backend = nil
        readyPipe = nil
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame,
              let url = message.frameInfo.request.url, url.scheme == localURL?.scheme,
              url.host == localURL?.host, url.port == localURL?.port,
              let preference = message.body as? String else { return }
        if message.name == sidebarPreferenceKey, preference == "shown" || preference == "hidden" {
            UserDefaults.standard.set(preference, forKey: sidebarPreferenceKey)
        } else if message.name == themePreferenceKey, preference == "light" || preference == "dark" {
            UserDefaults.standard.set(preference, forKey: themePreferenceKey)
            applyTheme(preference)
        } else if message.name == themePreferenceKey, preference == "system-light" || preference == "system-dark" {
            updateWindowColor(dark: preference == "system-dark")
        }
    }

    func webView(
        _ webView: WKWebView,
        runOpenPanelWith parameters: WKOpenPanelParameters,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping ([URL]?) -> Void
    ) {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = ["txt", "md", "csv", "json"].compactMap { UTType(filenameExtension: $0) }
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.beginSheetModal(for: window) { response in
            completionHandler(response == .OK ? panel.urls : nil)
        }
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor action: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        guard let url = action.request.url else {
            decisionHandler(.cancel)
            return
        }
        if url.scheme == "about" || (url.scheme == localURL?.scheme && url.host == localURL?.host && url.port == localURL?.port) {
            if action.targetFrame == nil {
                NSWorkspace.shared.open(url)
                decisionHandler(.cancel)
            } else {
                decisionHandler(.allow)
            }
            return
        }
        if action.navigationType == .linkActivated && ["http", "https"].contains(url.scheme ?? "") {
            NSWorkspace.shared.open(url)
        }
        decisionHandler(.cancel)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) { stopBackend() }
}

let application = NSApplication.shared
let delegate = DesktopApp()
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
