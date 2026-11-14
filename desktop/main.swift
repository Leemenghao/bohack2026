import AppKit
import WebKit

final class DesktopApp: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var backend: Process?
    private var readyPipe: Pipe?
    private var localURL: URL?
    private var readyOutput = Data()

    func applicationDidFinishLaunching(_ notification: Notification) {
        installMenu()
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1080, height: 760),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Research Agent"
        window.minSize = NSSize(width: 560, height: 420)
        webView = WKWebView()
        webView.navigationDelegate = self
        window.contentView = webView
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        showMessage("正在启动本地研究服务…")
        startBackend()
    }

    private func installMenu() {
        let menu = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Quit Research Agent", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
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
            <h1>Research Agent</h1><p>\(message)</p>
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
        process.standardError = FileHandle.nullDevice
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
        guard let end = readyOutput.firstIndex(of: 10) else { return }
        let line = String(decoding: readyOutput[..<end], as: UTF8.self)
        guard let port = Int(line), (1...65535).contains(port),
              let url = URL(string: "http://127.0.0.1:\(port)/") else { return }
        readyPipe?.fileHandleForReading.readabilityHandler = nil
        localURL = url
        webView.load(URLRequest(url: url))
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
