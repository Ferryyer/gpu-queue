#!/usr/bin/env python3
"""Compile the production Feishu view and inspect WebKit on a prepared Mac.

Only the Flutter messenger is replaced. Uses an empty local HTML document;
does not sign in, load the tenant, or access any account data.
"""
import platform
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent

STUBS = r'''
import Cocoa
protocol FlutterBinaryMessenger {}
protocol FlutterMessageCodec {}
final class FlutterStandardMessageCodec: NSObject, FlutterMessageCodec {
  static func sharedInstance() -> FlutterStandardMessageCodec { FlutterStandardMessageCodec() }
}
protocol FlutterPlatformViewFactory {
  func createArgsCodec() -> (FlutterMessageCodec & NSObjectProtocol)?
  func create(withViewIdentifier viewId: Int64, arguments args: Any?) -> NSView
}
struct FlutterMethodCall { let method: String; let arguments: Any? }
typealias FlutterResult = (Any?) -> Void
typealias FlutterMethodCallHandler = (FlutterMethodCall, @escaping FlutterResult) -> Void
let FlutterMethodNotImplemented = NSObject()
final class FlutterMethodChannel {
  static var events: [[String: Any]] = []
  static var handlers: [String: FlutterMethodCallHandler] = [:]
  let name: String
  init(name: String, binaryMessenger: FlutterBinaryMessenger) { self.name = name }
  func setMethodCallHandler(_ handler: FlutterMethodCallHandler?) {
    Self.handlers[name] = handler
  }
  func invokeMethod(_ method: String, arguments: Any?) {
    if let state = arguments as? [String: Any] { Self.events.append(state) }
  }
}
final class TestMessenger: FlutterBinaryMessenger {}
'''

TEST = r'''
import Cocoa
import WebKit

_ = NSApplication.shared
let tenant = FeishuTaskView.home.host!
for path in ["/next/messenger", "/next/messenger/"] {
  precondition(FeishuTaskView.isMessengerLanding(URL(string: "https://\(tenant)\(path)")!),
    "The messages landing page must return to tasks")
}
for url in [FeishuTaskView.home,
            URL(string: "https://\(tenant)/next/task/watched-tasks")!,
            URL(string: "https://\(tenant)/accounts/page/login/")!,
            URL(string: "https://\(tenant)/next/messenger/chat")!,
            URL(string: "https://\(tenant)/next/messenger?openChatId=fixture")!,
            URL(string: "https://example.com/next/messenger")!] {
  precondition(!FeishuTaskView.isMessengerLanding(url),
    "Task, sign-in, conversation and foreign URLs must retain normal navigation")
}
for embedded in [false, true] {
  let view = FeishuTaskView(viewId: embedded ? 2 : 1, messenger: TestMessenger(),
    arguments: ["script": "", "embedded": embedded])
  let web = view.subviews.compactMap { $0 as? WKWebView }.first!
  view.layout()
  precondition(web.url == nil, "A zero-size overview must not start navigation")
  precondition(web.configuration.websiteDataStore.isPersistent, "Sign-in must remain persistent")
  let suffix = web.configuration.applicationNameForUserAgent ?? ""
  precondition(suffix.range(of: #"^Version/\d+(?:\.\d+){0,2} Safari/605\.1\.15$"#,
    options: .regularExpression) != nil, "Missing Safari browser identity")

  view.webViewWebContentProcessDidTerminate(web)
  let error = FlutterMethodChannel.events.last?["error"] as? String
  precondition(error != nil, "A terminated off-window document must report its failure")
  FlutterMethodChannel.handlers["work.inspirequeue/feishu/\(embedded ? 2 : 1)"]?(
    FlutterMethodCall(method: "state", arguments: nil), { _ in })
  precondition(FlutterMethodChannel.events.last?["error"] as? String == error,
    "Querying state must not erase a navigation error")

  // Exercise WebKit's actual navigator.userAgent rather than a copied UA parser.
  web.loadHTMLString("<!doctype html><title>Local fixture</title>", baseURL: nil)
  var agent: String?
  let deadline = Date().addingTimeInterval(15)
  while agent == nil && Date() < deadline {
    if !web.isLoading {
      web.evaluateJavaScript("navigator.userAgent") { value, _ in agent = value as? String }
    }
    RunLoop.current.run(until: Date().addingTimeInterval(0.05))
  }
  precondition(agent?.contains(suffix) == true, "WebKit did not expose the configured identity")
  precondition(agent?.contains("AppleWebKit/") == true, "Keep the actual WebKit identity")
  web.stopLoading()
  print("PASS: embedded=\(embedded), desktop browser identity, zero-size navigation, persistent error")
}
'''


def main():
    if platform.system() != 'Darwin':
        raise SystemExit('Requires macOS, Xcode command-line tools and a working WebKit runtime')
    build = ROOT / 'build'
    build.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='feishu-browser-', dir=build) as folder:
        path = Path(folder)
        source = (ROOT / 'serverbox/macos/Runner/FeishuTaskView.swift').read_text()
        (path / 'FeishuTaskView.swift').write_text(source.replace('import FlutterMacOS\n', ''))
        (path / 'FlutterStubs.swift').write_text(STUBS)
        (path / 'main.swift').write_text(TEST)
        binary = path / 'feishu-browser-test'
        subprocess.run(['xcrun', 'swiftc', '-swift-version', '5',
                        str(path / 'FlutterStubs.swift'), str(path / 'FeishuTaskView.swift'),
                        str(path / 'main.swift'), '-o', str(binary)], check=True, timeout=90)
        subprocess.run([str(binary)], check=True, timeout=40)


if __name__ == '__main__':
    main()
