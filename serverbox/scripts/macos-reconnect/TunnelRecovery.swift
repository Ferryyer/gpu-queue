import AppKit
import Foundation
import Network

struct Configuration: Codable {
    var port: UInt16 = 22224
    var label = "local.servercat.linlishuo-tunnel"
    var launchctl = "/bin/launchctl"
    var statusFile = NSHomeDirectory() + "/.local/state/servercat/recovery-status.json"
    var interval: Double = 15
    var timeout: Double = 6
}

struct RetryPolicy {
    var failures = 0
    var attempts = 0
    var nextAllowed: TimeInterval = 0

    mutating func record(success: Bool, urgent: Bool, now: TimeInterval) -> Bool {
        if success {
            self = RetryPolicy()
            return false
        }
        failures += 1
        guard (urgent || failures >= 2), now >= nextAllowed else { return false }
        nextAllowed = now + min(120, 5 * pow(2, Double(min(attempts, 5))))
        attempts += 1
        failures = 0
        return true
    }
}

final class Recovery {
    let config: Configuration
    let queue = DispatchQueue(label: "serverbox.tunnel.recovery")
    let monitor = NWPathMonitor()
    var timer: DispatchSourceTimer?
    var signals: [DispatchSourceSignal] = []
    var observers: [NSObjectProtocol] = []
    var pending: DispatchWorkItem?
    var connection: NWConnection?
    var probeID = 0
    var policy = RetryPolicy()
    var online = false
    var sleeping = false
    var restarting = false
    var lastTick = Date().timeIntervalSince1970
    var lastState = ""

    init(_ config: Configuration) { self.config = config }

    func status(_ state: String, _ reason: String) {
        let value: [String: Any] = ["state": state, "reason": reason,
            "at": Date().timeIntervalSince1970, "pid": getpid(),
            "failures": policy.failures,
            "next_restart_in": max(0, policy.nextAllowed - ProcessInfo.processInfo.systemUptime)]
        do {
            let path = URL(fileURLWithPath: config.statusFile)
            try FileManager.default.createDirectory(at: path.deletingLastPathComponent(),
                withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]).write(to: path, options: .atomic)
            chmod(path.path, 0o600)
        } catch { fputs("Recovery status write failed: \(error)\n", stderr) }
        if state != lastState {
            print("\(ISO8601DateFormatter().string(from: Date())) \(state): \(reason)")
            fflush(stdout)
            lastState = state
        }
    }

    func cancelProbe() {
        probeID += 1
        connection?.cancel()
        connection = nil
    }

    func suspend() {
        sleeping = true
        pending?.cancel()
        cancelProbe()
        status("sleeping", "Mac sleeping; wait for wake")
    }

    func wake() {
        sleeping = false
        lastTick = Date().timeIntervalSince1970
        policy = RetryPolicy()
        cancelProbe()
        schedule(reason: "Mac wake", urgent: true)
    }

    func schedule(reason: String, urgent: Bool) {
        pending?.cancel()
        let item = DispatchWorkItem { self.check(reason: reason, urgent: urgent) }
        pending = item
        queue.asyncAfter(deadline: .now() + 2, execute: item)
    }

    func restart(_ reason: String) {
        guard !restarting, online, !sleeping else { return }
        restarting = true
        status("recovering", reason)
        let process = Process()
        process.executableURL = URL(fileURLWithPath: config.launchctl)
        process.arguments = ["kickstart", "-k", "gui/\(getuid())/\(config.label)"]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        process.terminationHandler = { child in
            self.queue.async {
                self.restarting = false
                if child.terminationStatus != 0 {
                    self.status("retrying", "launchctl returned \(child.terminationStatus)")
                }
            }
        }
        do { try process.run() }
        catch { restarting = false; status("retrying", "Cannot start launchctl: \(error)") }
        queue.asyncAfter(deadline: .now() + 30) {
            if process.isRunning {
                kill(process.processIdentifier, SIGKILL)
            }
        }
    }

    func check(reason: String, urgent: Bool = false) {
        guard online, !sleeping, !restarting, connection == nil else { return }
        probeID += 1
        let ticket = probeID
        let stream = NWConnection(host: "127.0.0.1", port: NWEndpoint.Port(rawValue: config.port)!, using: .tcp)
        connection = stream
        var bytes = Data()
        var accepted = false
        func finish(_ success: Bool) {
            guard ticket == self.probeID else { return }
            self.cancelProbe()
            // An absent listener can be an SSH process still authenticating.
            // launchd and SSH's connect timeout own that case. Repeatedly
            // killing it before it can bind would prevent recovery itself.
            if !accepted {
                self.status("waiting_tunnel", "SSH is connecting or launchd is retrying")
                return
            }
            let now = ProcessInfo.processInfo.systemUptime
            if self.policy.record(success: success, urgent: urgent, now: now) {
                self.restart("\(reason): forwarded SSH banner unavailable")
            } else {
                self.status(success ? "connected" : "retrying", reason)
            }
        }
        func receive() {
            stream.receive(minimumIncompleteLength: 1, maximumLength: 1024) { data, _, done, error in
                guard ticket == self.probeID else { return }
                if let data { bytes.append(data) }
                if bytes.split(separator: 10, omittingEmptySubsequences: false).dropLast().contains(where: { $0.starts(with: "SSH-2.0-".utf8) }) {
                    finish(true)
                } else if done || error != nil || bytes.count >= 1024 {
                    finish(false)
                } else { receive() }
            }
        }
        stream.stateUpdateHandler = { state in
            guard ticket == self.probeID else { return }
            switch state {
            case .ready: accepted = true; receive()
            case .failed: finish(false)
            default: break
            }
        }
        stream.start(queue: queue)
        queue.asyncAfter(deadline: .now() + config.timeout) { finish(false) }
    }

    func start() {
        queue.async { self.status("starting", "Monitoring the dedicated loopback SSH tunnel") }
        let center = NSWorkspace.shared.notificationCenter
        observers.append(center.addObserver(forName: NSWorkspace.willSleepNotification, object: nil, queue: .main) { _ in
            self.queue.async { self.suspend() }
        })
        observers.append(center.addObserver(forName: NSWorkspace.didWakeNotification, object: nil, queue: .main) { _ in
            self.queue.async { self.wake() }
        })
        monitor.pathUpdateHandler = { path in
            let wasOnline = self.online
            self.online = path.status == .satisfied
            if self.online {
                self.cancelProbe()
                if !wasOnline { self.policy = RetryPolicy() }
                self.schedule(reason: "Network available or changed", urgent: true)
            } else {
                self.pending?.cancel()
                self.cancelProbe()
                if !self.sleeping { self.status("waiting_network", "Network unavailable") }
            }
        }
        monitor.start(queue: queue)
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now() + config.interval, repeating: config.interval)
        timer.setEventHandler {
            let now = Date().timeIntervalSince1970
            let gap = now - self.lastTick
            self.lastTick = now
            if gap > max(45, self.config.interval * 3) { self.wake() }
            else { self.check(reason: "Periodic tunnel health check") }
        }
        timer.resume()
        self.timer = timer
        for number in [SIGUSR1, SIGUSR2, SIGTERM, SIGINT] {
            signal(number, SIG_IGN)
            let source = DispatchSource.makeSignalSource(signal: number, queue: queue)
            source.setEventHandler {
                if number == SIGUSR1 { self.wake() }
                else if number == SIGUSR2 { self.suspend() }
                else { self.pending?.cancel(); self.cancelProbe(); exit(0) }
            }
            source.resume()
            signals.append(source)
        }
    }
}

umask(0o077)
var configuration = Configuration()
if CommandLine.arguments.count == 3 && CommandLine.arguments[1] == "--config" {
    let path = CommandLine.arguments[2]
    let attributes = try FileManager.default.attributesOfItem(atPath: path)
    guard (attributes[.ownerAccountID] as? NSNumber)?.uint32Value == getuid(),
          ((attributes[.posixPermissions] as? NSNumber)?.intValue ?? 0o777) & 0o077 == 0 else {
        fputs("Configuration must belong to this user with mode 0600\n", stderr)
        exit(2)
    }
    configuration = try JSONDecoder().decode(Configuration.self, from: Data(contentsOf: URL(fileURLWithPath: path)))
}
guard configuration.interval >= 0.2, configuration.timeout >= 0.1, configuration.port > 0 else {
    fputs("Invalid recovery timing or port\n", stderr)
    exit(2)
}
let recovery = Recovery(configuration)
recovery.start()
RunLoop.main.run()
