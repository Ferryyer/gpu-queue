# Automatic Mac tunnel and ServerBox recovery

This configuration uses the existing dedicated SSH forward on `127.0.0.1:22224`.
ServerBox's normal desktop polling reconnects to that forward. Both layers
must keep retrying after sleep or a network outage.

## Client settings

In **Settings → Servers** set **Number of server reconnections** to **0**.
Despite the UI saying “0 times”, `lib/data/model/server/try_limiter.dart`
defines values at or below zero as **unlimited**, not disabled. Set this in the supported settings UI.
Automatic status refresh is enabled at five seconds (increased from three
seconds after the server thread-limit incident below).

The tunnel installer targets an existing personal SSH configuration; inspect
its host aliases and LaunchAgent labels before using it on another Mac. A manually closed
server stays closed, because the client's refresh loop excludes it. The
helper does not launch, quit or restart ServerBox or any terminal session.

## Native recovery helper

`TunnelRecovery.swift` uses only macOS Foundation, AppKit and Network.
It observes `NSWorkspace.willSleepNotification`, `didWakeNotification` and
`NWPathMonitor`. A periodic check also detects a missed long sleep gap.

- Sleep or network unavailability cancels checks; network return and wake
  schedule a fresh check after two seconds.
- Every 15 seconds, a bounded six-second loopback probe waits for an actual
  SSH banner. A local TCP accept alone cannot prove the tunnel is healthy.
- An absent listener is left to SSH's connection timeout and launchd's
  KeepAlive, so a slow authentication is allowed to complete.
- An accepted but wedged forward triggers a replacement after two failed
  checks; a wake/network recovery check may replace it on the first failure.
- Only `gui/<uid>/local.servercat.linlishuo-tunnel` is restarted. Retry backoff
  grows from 5 to 120 seconds using system uptime, and resets after success.
- One health probe and one launchctl operation can run at a time. Superseded
  callbacks cannot restart a newer connection. A launchctl operation is bounded.

The SSH LaunchAgent keeps its loopback-only listener and existing member
configuration. Both hops have keepalives every ten seconds, a two-miss limit
and one connection attempt per process. Connect timeouts allow 30 seconds
for the CPU connection and 20 for the gateway. Existing host-key checks,
identity restrictions and disabled agent forwarding remain in effect.
No keys are copied, no server commands are executed, and GPU jobs are not
restarted or resubmitted.

Install/update as the logged-in Mac user:

```sh
python3 scripts/macos-reconnect/install.py
```

This compiles a small native executable without Flutter or full Xcode. It
backs up the existing files, updates the SSH LaunchAgent, and installs
`~/Library/LaunchAgents/local.serverbox.linlishuo-recovery.plist` with
`~/.local/libexec/serverbox-tunnel-recovery`.
Both agents load at login. It restores the previous agents if installation
fails. The first installation briefly replaces only the dedicated tunnel.

## Diagnostics and rollback

Read `~/.local/state/servercat/recovery-status.json` for `connected`,
`waiting_network`, `waiting_tunnel`, `sleeping` or `recovering`. This private
file records the last check and retry delay; logs are in `recovery.log` and
the existing `tunnel-error.log` in that directory.

Backups are in `~/.local/state/servercat/backups/reconnect-<timestamp>/`.
To remove this recovery setup, unload the recovery LaunchAgent first with
`launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/local.serverbox.linlishuo-recovery.plist`,
then unload the SSH agent, restore the desired backup of its `.plist` and
load it again with `launchctl bootstrap`. Move the recovery `.plist` out of
`~/Library/LaunchAgents` to prevent it loading next login. Set the client's
retry count back to 2 if the old behavior is wanted. Do not unload unrelated
agents or remove SSH keys and known-host files.

The helper recovers client transport when the gateway is reachable. It does
not bypass changed host keys or interactive authentication prompts. A closed
connection before the SSH banner can also come from the Mac's proxy route;
check the route before concluding that the remote gateway is unavailable.

