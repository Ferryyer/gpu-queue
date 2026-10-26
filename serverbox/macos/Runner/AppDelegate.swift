import Cocoa
import FlutterMacOS

@main
class AppDelegate: FlutterAppDelegate {
  override func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
    return true
  }

  override func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool {
    return true
  }

  /// AirDrop, "Open With", and a `.sbxsrv` double-clicked in the Finder all
  /// arrive here.
  ///
  /// On a cold open this runs *before* `applicationDidFinishLaunching`, so
  /// there is no engine and no channel yet — which is why [IncomingShare]
  /// holds the bytes rather than delivering them.
  /// `super` first and unconditionally, the same as the iOS scene delegate:
  /// `FlutterAppDelegate` implements this and forwards it to every registered
  /// plugin through `handleOpenURLs:`, so swallowing it would stop any plugin
  /// answering a custom scheme or a deep link — for the sake of a file this
  /// app may not even have been handed.
  override func application(_ application: NSApplication, open urls: [URL]) {
    super.application(application, open: urls)
    IncomingShare.accept(urls)
  }

  override func applicationDidFinishLaunching(_ notification: Notification) {
    // Subscribed at launch because delivery is on the system's schedule: a
    // payload for a crash arrives some time after the launch following it, and
    // a subscriber registered later simply misses that window.
    if #available(macOS 12.0, *) {
      CrashDiagnostics.shared.start()
    }

    if let controller = mainFlutterWindow?.contentViewController as? FlutterViewController {
      let updateChannel = FlutterMethodChannel(
        name: "work.gpuqueue/update", binaryMessenger: controller.engine.binaryMessenger)
      updateChannel.setMethodCallHandler { call, result in
        GPUQueueUpdate.handle(call, result)
      }
      let channel = FlutterMethodChannel(name: "about", binaryMessenger: controller.engine.binaryMessenger)
      channel.setMethodCallHandler { (call: FlutterMethodCall, result: @escaping FlutterResult) in
        if call.method == "showAboutPanel" {
          NSApp.orderFrontStandardAboutPanel(nil)
          result(nil)
        } else {
          result(FlutterMethodNotImplemented)
        }
      }

      // The same channel name the other platforms use, so the Dart side has
      // one call rather than a per-platform branch. Only the one method: the
      // rest of `main_chan` is Android and iOS specific.
      let mainChannel = FlutterMethodChannel(
        name: "tech.lolli.toolbox/main_chan",
        binaryMessenger: controller.engine.binaryMessenger
      )
      // Its own channel, for the same reason the tray has one. Only ever
      // carries a nudge; the payload still leaves through `takeOpenedShare` or
      // `takeOpenedLink`.
      let shareChannel = FlutterMethodChannel(
        name: "tech.lolli.toolbox/incoming_share",
        binaryMessenger: controller.engine.binaryMessenger
      )
      // Captured strongly, and that is the whole of it: the channel is a
      // local, so nothing else holds one. Captured weakly it was deallocated
      // the moment this method returned and every later nudge went to nil.
      // There is no cycle to break: the closure is owned by `IncomingShare`,
      // not by the channel.
      IncomingShare.onArrival = {
        // Already on the main thread, since every URL callback is; hopped
        // explicitly anyway, because a channel call from anywhere else is
        // undefined rather than merely late.
        DispatchQueue.main.async {
          shareChannel.invokeMethod("opened", arguments: nil)
        }
      }

      // Its own channel: the tray talks in both directions and the handler
      // above is already taken.
      if #available(macOS 10.15, *) {
        TrayIcon.shared.attach(FlutterMethodChannel(
          name: "tech.lolli.toolbox/tray",
          binaryMessenger: controller.engine.binaryMessenger
        ))
      }

      // The system's "Reduce motion", which the engine does not pass on the
      // way iOS's does. Asked once, then told on every change.
      let motionChannel = FlutterMethodChannel(
        name: "tech.lolli.toolbox/motion",
        binaryMessenger: controller.engine.binaryMessenger
      )
      motionChannel.setMethodCallHandler { (call: FlutterMethodCall, result: @escaping FlutterResult) in
        if call.method == "reduceMotion" {
          result(NSWorkspace.shared.accessibilityDisplayShouldReduceMotion)
        } else {
          result(FlutterMethodNotImplemented)
        }
      }
      NSWorkspace.shared.notificationCenter.addObserver(
        forName: NSWorkspace.accessibilityDisplayOptionsDidChangeNotification,
        object: nil,
        queue: .main
      ) { _ in
        motionChannel.invokeMethod(
          "reduceMotionChanged",
          arguments: NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        )
      }

      mainChannel.setMethodCallHandler { (call: FlutterMethodCall, result: @escaping FlutterResult) in
        // What MetricKit has reported since this was last asked. Cleared by
        // the read — the caller writes them into a log that persists, and
        // keeping a copy here would report the same crash forever.
        if call.method == "takeCrashDiagnostics" {
          if #available(macOS 12.0, *) {
            result(CrashDiagnostics.take())
          } else {
            result(nil)
          }
        } else if call.method == "takeOpenedShare" {
          result(IncomingShare.take())
        } else if call.method == "takeOpenedLink" {
          result(IncomingShare.takeLink())
        } else {
          result(FlutterMethodNotImplemented)
        }
      }
    }
    super.applicationDidFinishLaunching(notification)
  }
}

private enum GPUQueueUpdate {
  static var installing = false
  static var activeWork: URL?
  static var statusURL: URL {
    FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
      .appendingPathComponent("GPU Queue/Updater/status.json")
  }
  static func readState() -> [String: Any]? {
    guard let data = try? Data(contentsOf: statusURL) else { return nil }
    return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
  }
  static func writeState(_ value: [String: Any]) throws {
    try JSONSerialization.data(withJSONObject: value).write(to: statusURL, options: .atomic)
  }
  static func handle(_ call: FlutterMethodCall, _ result: @escaping FlutterResult) {
    let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String
    switch call.method {
    case "installedBuild":
      result(build)
    case "installStatus":
      let state = readState()
      if state?["phase"] as? String == "failed" { installing = false }
      result(state)
    case "cancelInstall":
      if let work = activeWork { try? Data().write(to: work.appendingPathComponent("cancel")) }
      installing = false
      result(nil)
    case "confirmLaunch":
      if var state = readState(), state["phase"] as? String == "awaiting_launch",
         state["build"] as? String == build,
         state["destination"] as? String == Bundle.main.bundleURL.standardizedFileURL.path {
        state["phase"] = "complete"
        try? writeState(state)
      }
      result(nil)
    case "lastResult":
      if var state = readState(), state["notified"] as? Bool != true,
         ["complete", "rolled_back"].contains(state["phase"] as? String ?? "") {
        state["notified"] = true
        try? writeState(state)
        result(state)
      } else { result(nil) }
    case "install":
      guard !installing else {
        result(FlutterError(code: "busy", message: "正在安装更新", details: nil)); return
      }
      guard let args = call.arguments as? [String: Any],
            let dmg = args["dmg"] as? String, let hash = args["sha256"] as? String,
            let nextBuild = args["build"] as? Int,
            hash.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil,
            nextBuild > 0,
            let bundleID = Bundle.main.bundleIdentifier else {
        result(FlutterError(code: "invalid_update", message: "更新信息缺少有效的安装包路径、校验和或版本号，请重新检查更新。", details: nil)); return
      }
      guard let currentBuild = Int(build ?? ""), currentBuild > 0 else {
        result(FlutterError(code: "invalid_current_build", message: "无法读取当前应用版本，请重新打开应用后重试。", details: nil)); return
      }
      guard nextBuild > currentBuild else {
        result(FlutterError(code: "already_current", message: "当前应用已是此版本或更新版本，无需重复安装。", details: nil)); return
      }
      installing = true
      let destination = Bundle.main.bundleURL.standardizedFileURL
      let helper = destination.appendingPathComponent("Contents/Helpers/GPUQueueUpdater")
      let id = UUID().uuidString
      let work = URL(fileURLWithPath: dmg).deletingLastPathComponent()
      activeWork = work
      let plan = work.appendingPathComponent("plan.json")
      let statePath = statusURL
      DispatchQueue.global(qos: .userInitiated).async {
        do {
          let fm = FileManager.default
          try fm.createDirectory(at: statePath.deletingLastPathComponent(), withIntermediateDirectories: true,
                                 attributes: [.posixPermissions: 0o700])
          let body: [String: Any] = ["id": id, "destination": destination.path,
            "dmg": dmg, "sha256": hash, "build": String(nextBuild), "bundleID": bundleID,
            "pid": ProcessInfo.processInfo.processIdentifier, "status": statePath.path]
          try JSONSerialization.data(withJSONObject: body).write(to: plan, options: .atomic)
          let process = Process()
          process.executableURL = helper
          process.arguments = [plan.path]
          let logURL = statePath.deletingLastPathComponent().appendingPathComponent("install.log")
          if !fm.fileExists(atPath: logURL.path) { fm.createFile(atPath: logURL.path, contents: nil) }
          let log = try FileHandle(forWritingTo: logURL)
          try log.truncate(atOffset: 0)
          process.standardOutput = log
          process.standardError = log
          try process.run()
          // Process has inherited its log descriptor; it survives the app exiting.
          try log.close()
          let deadline = Date().addingTimeInterval(180)
          while Date() < deadline {
            if let state = readState(), state["id"] as? String == id {
              if state["phase"] as? String == "ready" {
                DispatchQueue.main.async {
                  result(nil)
                  DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { NSApp.terminate(nil) }
                }
                return
              }
              if state["phase"] as? String == "failed" {
                throw NSError(domain: "GPUQueueUpdater", code: 1,
                              userInfo: [NSLocalizedDescriptionKey: state["message"] as? String ?? "更新准备失败"])
              }
            }
            if !process.isRunning { throw NSError(domain: "GPUQueueUpdater", code: 2,
              userInfo: [NSLocalizedDescriptionKey: "安装器未能启动，请查看安装日志。"] ) }
            Thread.sleep(forTimeInterval: 0.1)
          }
          // A slow copy can finish after this deadline. Explicit cancellation
          // prevents that helper from installing later when the user quits.
          try Data().write(to: work.appendingPathComponent("cancel"))
          throw NSError(domain: "GPUQueueUpdater", code: 3,
            userInfo: [NSLocalizedDescriptionKey: "更新准备超时，应用仍在运行，请稍后重试。"])
        } catch {
          DispatchQueue.main.async {
            installing = false
            result(FlutterError(code: "install_failed", message: error.localizedDescription, details: nil))
          }
        }
      }
    default: result(FlutterMethodNotImplemented)
    }
  }
}
