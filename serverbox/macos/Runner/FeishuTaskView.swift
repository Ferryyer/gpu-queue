import Cocoa
import FlutterMacOS
import WebKit

/// A top-level WebKit document, not an iframe. Feishu owns authentication;
/// its cookies stay in WebKit's persistent store and never cross the channel.
final class FeishuTaskFactory: NSObject, FlutterPlatformViewFactory {
  private let messenger: FlutterBinaryMessenger
  init(messenger: FlutterBinaryMessenger) { self.messenger = messenger }
  func createArgsCodec() -> (FlutterMessageCodec & NSObjectProtocol)? {
    FlutterStandardMessageCodec.sharedInstance()
  }
  func create(withViewIdentifier viewId: Int64, arguments args: Any?) -> NSView {
    FeishuTaskView(viewId: viewId, messenger: messenger, arguments: args)
  }
}

final class FeishuTaskView: NSView, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
  static let home = URL(string: "https://uqyv5nolng8.feishu.cn/next/task/my-tasks")!
  private let channel: FlutterMethodChannel
  private let web: WKWebView
  private let script: String
  private let embedded: Bool
  private var enabled: Bool
  private var dark: Bool
  private var popupWindows: [NSWindow] = []
  private var loadingObservation: NSKeyValueObservation?
  private var activeObservation: NSObjectProtocol?
  private var pageError: String?
  private var needsRecovery = false
  private var recoveryAttempted = false
  private var initialNavigationStarted = false

  init(viewId: Int64, messenger: FlutterBinaryMessenger, arguments: Any?) {
    let args = arguments as? [String: Any] ?? [:]
    script = args["script"] as? String ?? ""
    embedded = args["embedded"] as? Bool ?? false
    dark = args["dark"] as? Bool ?? false
    enabled = UserDefaults.standard.object(forKey: "inspire.feishu.appearance") as? Bool ?? true
    channel = FlutterMethodChannel(name: "work.inspirequeue/feishu/\(viewId)", binaryMessenger: messenger)
    let config = WKWebViewConfiguration()
    config.websiteDataStore = .default()
    // macOS WKWebView omits Version/ and Safari/ by default. Feishu's browser
    // check cannot identify that UA even though it is the system WebKit engine.
    let safari = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.Safari")
      .flatMap { Bundle(url: $0) }
    let installedVersion = safari?.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String
    let version = installedVersion.flatMap {
      $0.range(of: #"^\d+(?:\.\d+){0,2}$"#, options: .regularExpression) != nil ? $0 : nil
    } ?? "16.0" // Minimum bundled Safari for the application's macOS 13 floor.
    config.applicationNameForUserAgent = "Version/\(version) Safari/605.1.15"
    web = WKWebView(frame: .zero, configuration: config)
    super.init(frame: .zero)
    web.navigationDelegate = self
    web.uiDelegate = self
    web.allowsBackForwardNavigationGestures = true
    web.autoresizingMask = [.width, .height]
    addSubview(web)
    installScript()
    loadingObservation = web.observe(\.isLoading, options: [.new]) { [weak self] _, _ in
      self?.sendState()
    }
    channel.setMethodCallHandler { [weak self] call, result in
      guard let self = self else { result(nil); return }
      switch call.method {
      case "state": self.sendState(); result(nil)
      case "reload": self.reloadPage(); result(nil)
      case "refresh":
        // Do not interrupt sign-in, navigation, or a native attachment dialog.
        let url = self.web.url ?? Self.home
        if Self.isFeishu(url),
           url.host == Self.home.host, url.path.hasPrefix("/next/task/"),
           !self.web.isLoading, self.window?.attachedSheet == nil,
           !self.popupWindows.contains(where: { $0.isVisible }) {
          self.reloadPage()
        }
        result(nil)
      case "home": self.web.load(URLRequest(url: Self.home)); result(nil)
      case "back": if self.web.canGoBack { self.web.goBack() }; result(nil)
      case "appearance":
        self.enabled = call.arguments as? Bool ?? true
        UserDefaults.standard.set(self.enabled, forKey: "inspire.feishu.appearance")
        self.installScript()
        self.web.evaluateJavaScript("window.InspireTaskAppearance?.setEnabled(\(self.enabled));", completionHandler: nil)
        self.sendState(); result(nil)
      case "dark":
        self.dark = call.arguments as? Bool ?? false
        self.installScript()
        self.web.evaluateJavaScript("window.InspireTaskAppearance?.setDark(\(self.dark));", completionHandler: nil)
        result(nil)
      default: result(FlutterMethodNotImplemented)
      }
    }
    activeObservation = NotificationCenter.default.addObserver(
      forName: NSApplication.didBecomeActiveNotification, object: nil, queue: .main
    ) { [weak self] _ in self?.recoverIfNeeded() }
  }
  required init?(coder: NSCoder) { fatalError("init(coder:) is unavailable") }
  override func layout() {
    super.layout()
    web.frame = bounds
    // The overview can be constructed before its scroll panel is laid out.
    // Start the document with a real viewport, not a transient zero-size frame.
    if !initialNavigationStarted && bounds.width > 0 && bounds.height > 0 {
      initialNavigationStarted = true
      web.load(URLRequest(url: Self.home))
    }
  }
  override func viewDidMoveToWindow() {
    super.viewDidMoveToWindow()
    recoverIfNeeded()
  }
  deinit {
    if let observer = activeObservation { NotificationCenter.default.removeObserver(observer) }
    channel.setMethodCallHandler(nil)
    web.stopLoading()
    popupWindows.forEach { $0.close() }
  }

  private func reloadPage() {
    pageError = nil
    // reload() has no navigation to repeat after an initial provisional failure.
    if web.reload() == nil { web.load(URLRequest(url: Self.home)) }
  }
  private func recoverIfNeeded() {
    guard needsRecovery, !recoveryAttempted, window != nil, NSApp.isActive else { return }
    needsRecovery = false
    recoveryAttempted = true
    reloadPage()
  }

  private func installScript() {
    let content = web.configuration.userContentController
    content.removeAllUserScripts()
    let options = "window.__inspireTaskOptions={enabled:\(enabled),dark:\(dark),embedded:\(embedded)};\n"
    content.addUserScript(WKUserScript(source: options + script,
      injectionTime: .atDocumentStart, forMainFrameOnly: true))
  }
  private func sendState(error: String? = nil) {
    if let error = error { pageError = error }
    // Never send the full URL: login redirects can include authorization codes.
    channel.invokeMethod("state", arguments: [
      "loading": web.isLoading, "canGoBack": web.canGoBack, "enabled": enabled,
      "error": pageError as Any? ?? NSNull()
    ])
  }
  static func isFeishu(_ url: URL) -> Bool {
    guard url.scheme == "https", let host = url.host?.lowercased() else { return false }
    return ["feishu.cn", "larksuite.com"].contains { host == $0 || host.hasSuffix("." + $0) }
  }
  func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
               decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
    guard let url = action.request.url else { decisionHandler(.cancel); return }
    if action.shouldPerformDownload && (Self.isFeishu(url) || url.scheme == "blob") {
      decisionHandler(.download); return
    }
    // Subframes may host Feishu's identity provider. They get no native bridge.
    if action.targetFrame?.isMainFrame == false {
      decisionHandler(url.scheme == "https" || url.absoluteString == "about:blank" ? .allow : .cancel)
      return
    }
    if Self.isFeishu(url) || url.absoluteString == "about:blank" {
      decisionHandler(.allow); return
    }
    decisionHandler(.cancel)
    if action.navigationType == .linkActivated && ["https", "http", "mailto", "lark", "feishu"].contains(url.scheme ?? "") {
      NSWorkspace.shared.open(url)
    } else {
      sendState(error: "此登录方式需要外部浏览器。可切换飞书扫码登录，或在浏览器中打开任务。")
    }
  }
  func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
    if webView === web {
      pageError = nil
      needsRecovery = false
      recoveryAttempted = false
      sendState()
    }
  }
  func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
    if webView === web { pageError = nil; sendState() }
  }
  func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
               decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
    decisionHandler(response.canShowMIMEType ? .allow : .download)
  }
  func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
    download.delegate = self
  }
  func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
    download.delegate = self
  }
  func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
    let panel = NSSavePanel()
    panel.nameFieldStringValue = (suggestedFilename as NSString).lastPathComponent
    if let window = self.window {
      panel.beginSheetModal(for: window) { completionHandler($0 == .OK ? panel.url : nil) }
    } else { completionHandler(nil) }
  }
  func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
    sendState(error: "附件下载未完成，请重试或在浏览器中下载。")
  }
  func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
    report(error, from: webView)
  }
  func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
    report(error, from: webView)
  }
  private func report(_ error: Error, from view: WKWebView) {
    if (error as NSError).code == NSURLErrorCancelled { return }
    if view === web { sendState(error: "飞书页面未能加载，请检查网络后重试。") }
  }
  func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
    if webView === web {
      needsRecovery = true
      sendState(error: "网页进程已结束，请刷新页面。")
      // Kept-alive overview and sidebar documents can terminate independently.
      // Retry once; a second termination before didFinish leaves manual retry.
      recoverIfNeeded()
    }
  }
  func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
               for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
    guard let url = action.request.url, Self.isFeishu(url) else { return nil }
    // A real child web view preserves window.opener for sign-in popups.
    configuration.applicationNameForUserAgent = web.configuration.applicationNameForUserAgent
    let popup = WKWebView(frame: NSRect(x: 0, y: 0, width: 760, height: 680), configuration: configuration)
    popup.navigationDelegate = self
    popup.uiDelegate = self
    let window = NSWindow(contentRect: popup.frame, styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
    window.title = "飞书 · Inspire Queue"
    window.isReleasedWhenClosed = false
    window.contentView = popup
    window.center()
    popupWindows.removeAll { !$0.isVisible }
    popupWindows.append(window)
    window.makeKeyAndOrderFront(nil)
    return popup
  }
  func webViewDidClose(_ webView: WKWebView) {
    guard webView !== web else { return }
    popupWindows.filter { $0.contentView === webView }.forEach { $0.close() }
    popupWindows.removeAll { $0.contentView === webView }
  }
  func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
               initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
    let alert = NSAlert(); alert.messageText = "飞书"; alert.informativeText = message
    alert.addButton(withTitle: "好")
    if let window = webView.window { alert.beginSheetModal(for: window) { _ in completionHandler() } }
    else { completionHandler() }
  }
  func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
               initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
    let alert = NSAlert(); alert.messageText = "飞书"; alert.informativeText = message
    alert.addButton(withTitle: "确定"); alert.addButton(withTitle: "取消")
    if let window = webView.window { alert.beginSheetModal(for: window) { completionHandler($0 == .alertFirstButtonReturn) } }
    else { completionHandler(false) }
  }
  func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
               initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
    let panel = NSOpenPanel()
    panel.allowsMultipleSelection = parameters.allowsMultipleSelection
    panel.canChooseDirectories = parameters.allowsDirectories
    if let window = webView.window {
      panel.beginSheetModal(for: window) { response in completionHandler(response == .OK ? panel.urls : nil) }
    } else { completionHandler(nil) }
  }
}
