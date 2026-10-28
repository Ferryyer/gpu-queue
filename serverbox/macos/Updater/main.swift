import Cocoa
import CryptoKit
import Darwin

// Runs independently of Flutter so replacing the app never depends on its lifetime.
let fm = FileManager.default
struct Failure: LocalizedError {
  let message: String
  var errorDescription: String? { message }
}
func fail(_ message: String) throws -> Never { throw Failure(message: message) }
func read(_ url: URL) throws -> [String: Any] {
  guard let value = try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any] else {
    try fail("Invalid update state")
  }
  return value
}
func write(_ value: [String: Any], _ url: URL) throws {
  try JSONSerialization.data(withJSONObject: value).write(to: url, options: .atomic)
}
func command(_ executable: String, _ args: [String]) throws {
  let process = Process()
  process.executableURL = URL(fileURLWithPath: executable)
  process.arguments = args
  // Do not use an undrained pipe: codesign/ditto can produce large diagnostics.
  process.standardOutput = FileHandle.standardError
  process.standardError = FileHandle.standardError
  try process.run()
  process.waitUntilExit()
  if process.terminationStatus != 0 { try fail("\(URL(fileURLWithPath: executable).lastPathComponent) failed (\(process.terminationStatus))") }
}
func bundleInfo(_ app: URL) throws -> [String: Any] {
  let data = try Data(contentsOf: app.appendingPathComponent("Contents/Info.plist"))
  guard let info = try PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any] else {
    try fail("Invalid application bundle")
  }
  return info
}
func launch(_ app: URL) throws -> NSRunningApplication {
  var finished = false
  var application: NSRunningApplication?
  var launchError: Error?
  let config = NSWorkspace.OpenConfiguration()
  config.activates = true
  config.createsNewApplicationInstance = true
  NSWorkspace.shared.openApplication(at: app, configuration: config) { running, error in
    application = running
    launchError = error
    finished = true
  }
  let deadline = Date().addingTimeInterval(30)
  while !finished && Date() < deadline {
    RunLoop.current.run(until: Date().addingTimeInterval(0.05))
  }
  guard let application = application else { throw launchError ?? Failure(message: "Application did not launch") }
  return application
}

var statusURL: URL?
var state: [String: Any] = [:]
var stage: URL?
var mount: URL?
var lockFD: Int32 = -1
var ownedWork: URL?
func status(_ phase: String, _ message: String? = nil) throws {
  state["phase"] = phase
  state["message"] = message
  state["notified"] = false
  if let url = statusURL { try write(state, url) }
}

do {
  guard CommandLine.arguments.count == 2 else { try fail("Expected a private update plan") }
  let planURL = URL(fileURLWithPath: CommandLine.arguments[1])
  let plan = try read(planURL)
  func string(_ key: String) throws -> String {
    guard let value = plan[key] as? String, !value.isEmpty else { try fail("Missing \(key)") }
    return value
  }
  let destination = URL(fileURLWithPath: try string("destination")).standardizedFileURL
  let work = planURL.deletingLastPathComponent()
  ownedWork = work
  let dmg = URL(fileURLWithPath: try string("dmg"))
  let bundleID = try string("bundleID")
  let build = try string("build")
  let id = try string("id")
  let expectedHash = try string("sha256")
  let oldPID = (plan["pid"] as? NSNumber)?.int32Value ?? 0
  let quitTimeout = (plan["quitTimeout"] as? Double) ?? 60
  let launchTimeout = (plan["launchTimeout"] as? Double) ?? 45
  let output = URL(fileURLWithPath: try string("status"))
  try fm.createDirectory(at: output.deletingLastPathComponent(), withIntermediateDirectories: true,
                         attributes: [.posixPermissions: 0o700])
  lockFD = Darwin.open(output.deletingLastPathComponent().appendingPathComponent("install.lock").path,
                       O_CREAT | O_RDWR, 0o600)
  guard lockFD >= 0, flock(lockFD, LOCK_EX | LOCK_NB) == 0 else { try fail("Another installation is running") }
  statusURL = output
  state = ["id": id, "build": build, "destination": destination.path, "phase": "preparing"]
  try status("preparing")
  let parent = destination.deletingLastPathComponent()
  guard destination.pathExtension == "app", fm.isWritableFile(atPath: parent.path),
        !destination.path.contains("/AppTranslocation/"),
        try bundleInfo(destination)["CFBundleIdentifier"] as? String == bundleID,
        let old = NSRunningApplication(processIdentifier: oldPID),
        old.bundleURL?.standardizedFileURL == destination else {
    try fail("请先将应用移到可写的 Applications 文件夹后重试。")
  }
  // Read in chunks: a DMG must not be loaded entirely into the helper's memory.
  let handle = try FileHandle(forReadingFrom: dmg)
  var hash = SHA256()
  while let bytes = try handle.read(upToCount: 1024 * 1024), !bytes.isEmpty { hash.update(data: bytes) }
  try handle.close()
  let actual = hash.finalize().map { String(format: "%02x", $0) }.joined()
  guard expectedHash.count == 64, actual == expectedHash else { try fail("安装包 SHA-256 校验失败，旧应用未改动。") }
  try command("/usr/bin/hdiutil", ["verify", dmg.path])
  let volume = work.appendingPathComponent("volume", isDirectory: true)
  try fm.createDirectory(at: volume, withIntermediateDirectories: true)
  mount = volume
  try command("/usr/bin/hdiutil", ["attach", dmg.path, "-readonly", "-nobrowse", "-mountpoint", volume.path])
  let brandedCandidate = volume.appendingPathComponent("Inspire Queue.app")
  let candidate = fm.fileExists(atPath: brandedCandidate.path)
    ? brandedCandidate : volume.appendingPathComponent("GPU Queue.app")
  let info = try bundleInfo(candidate)
  guard info["CFBundleIdentifier"] as? String == bundleID,
        info["CFBundleVersion"] as? String == build,
        let currentBuild = try bundleInfo(destination)["CFBundleVersion"] as? String,
        let currentNumber = Int(currentBuild), let nextNumber = Int(build), nextNumber > currentNumber else {
    try fail("安装包标识或版本不匹配，旧应用未改动。")
  }
  try command("/usr/bin/codesign", ["--verify", "--deep", "--strict", candidate.path])
  guard let executable = info["CFBundleExecutable"] as? String, !executable.contains("/"), !executable.isEmpty else {
    try fail("安装包缺少应用程序。")
  }
  #if arch(arm64)
  let architecture = "arm64"
  #else
  let architecture = "x86_64"
  #endif
  try command("/usr/bin/lipo", [candidate.appendingPathComponent("Contents/MacOS/\(executable)").path,
                              "-verify_arch", architecture])
  let staged = parent.appendingPathComponent(".InspireQueue-staged-\(id).app")
  stage = staged
  try command("/usr/bin/ditto", [candidate.path, staged.path])
  try command("/usr/bin/codesign", ["--verify", "--deep", "--strict", staged.path])
  try command("/usr/bin/hdiutil", ["detach", "-force", volume.path])
  mount = nil
  let backup = parent.appendingPathComponent("Inspire Queue.previous-\(currentBuild)-\(id).app")
  state["backup"] = backup.path
  guard !fm.fileExists(atPath: work.appendingPathComponent("cancel").path) else { try fail("更新已取消，旧应用未改动。") }
  try status("ready")
  let quitDeadline = Date().addingTimeInterval(quitTimeout)
  while !old.isTerminated && Date() < quitDeadline {
    guard !fm.fileExists(atPath: work.appendingPathComponent("cancel").path) else { try fail("更新已取消，旧应用未改动。") }
    RunLoop.current.run(until: Date().addingTimeInterval(0.1))
  }
  guard !fm.fileExists(atPath: work.appendingPathComponent("cancel").path) else { try fail("更新已取消，旧应用未改动。") }
  guard old.isTerminated else { try fail("等待应用退出超时，旧应用未改动。请退出后重试。") }
  try fm.moveItem(at: destination, to: backup)
  var installed = false
  var running: NSRunningApplication?
  do {
    try fm.moveItem(at: staged, to: destination)
    stage = nil
    installed = true
    try status("awaiting_launch")
    running = try launch(destination)
    let deadline = Date().addingTimeInterval(launchTimeout)
    var confirmed = false
    while Date() < deadline {
      if let latest = try? read(output), latest["id"] as? String == id,
         latest["phase"] as? String == "complete" { confirmed = true; break }
      if running?.isTerminated == true { break }
      RunLoop.current.run(until: Date().addingTimeInterval(0.1))
    }
    guard confirmed else { try fail("新版未能完成启动，已恢复上一版本。") }
    // Keep the previous app as a manual fallback; never touch preferences or Keychain.
  } catch {
    if let app = running, !app.isTerminated {
      app.terminate()
      let deadline = Date().addingTimeInterval(5)
      while !app.isTerminated && Date() < deadline { RunLoop.current.run(until: Date().addingTimeInterval(0.1)) }
      if !app.isTerminated { app.forceTerminate() }
      let forceDeadline = Date().addingTimeInterval(5)
      while !app.isTerminated && Date() < forceDeadline { RunLoop.current.run(until: Date().addingTimeInterval(0.1)) }
      guard app.isTerminated else { try fail("新版无法退出；备份保留在 \(backup.path)，请手动恢复。") }
    }
    if installed {
      try fm.moveItem(at: destination, to: parent.appendingPathComponent("Inspire Queue.failed-\(id).app"))
    }
    try fm.moveItem(at: backup, to: destination)
    try status("rolled_back", error.localizedDescription)
    _ = try launch(destination)
  }
  try? fm.removeItem(at: work)
} catch {
  try? status("failed", error.localizedDescription)
  fputs("\(error.localizedDescription)\n", stderr)
  if let volume = mount {
    do { try command("/usr/bin/hdiutil", ["detach", "-force", volume.path]); mount = nil }
    catch { fputs("Could not detach update volume: \(error)\n", stderr) }
  }
  if let staged = stage { try? fm.removeItem(at: staged) }
  if mount == nil, let work = ownedWork { try? fm.removeItem(at: work) }
  exit(1)
}
if lockFD >= 0 { flock(lockFD, LOCK_UN); close(lockFD) }
