# ServerBox account thread status

`status.py` is a read-only Linux status command for the current real UID.
It sums the `Threads` fields in owned, visible `/proc/<pid>/status` files,
groups them by process name, and lists the eight largest groups with the
largest process PID. It does not read command-line arguments or credentials.

The first line contains the total (`470 个线程`); the second contains the
process count, account and sampling time. Tap **账号线程占用** to see program
groups and inherited limits.
ServerBox's ordinary **进程** page also shows thread counts in process details.
The CPU card's logical CPU count is a different measurement.

The helper reports `Max processes` (RLIMIT_NPROC) separately for its own
process and the owned service supervisor named in
`~/.local/state/markflow-services/status.json`. Linux uses this limit for
thread creation, but it is inherited per process: an unlimited or higher-limit
session may create threads beyond a different session's limit. This is not a
single account-wide quota or a CPU/bandwidth percentage. Counts cover only
the current process namespace; concurrent exits and unreadable files can make
the snapshot partial. A three-second scan budget marks incomplete output.

## Current installation

The signed ServerBox client reads the command from the CPU account's private
`~/.config/server_box/custom_cmds/10000_6LSm5Y-357q_56iL5Y2g55So`.
Its contents are `/usr/bin/python3 - <<'SERVERBOX_THREADS_PY'`, followed by
the complete `status.py` source and a `SERVERBOX_THREADS_PY` closing line.
The filename uses a five-digit order and padded URL-safe Base64 of the UTF-8
title. Existing GPU monitoring commands are preserved.

This uses the client's existing five-second refresh and custom-command
timeout; it starts one short Python process per sample, not a background
service. Reconnection automatically resumes reads of the same remote file.
No application rebuild or additional network port is required.

On 2026-10-23 the command was installed and verified in the live Mac client's
expanded card. A direct sample took 0.033 seconds and showed 476 threads in
93 processes; the next UI sample showed 474 in 92. The sampler inherited
4096/4096 while the service supervisor retained 512/512. These are historical
samples, not fixed quotas or current values.

For rollback, remove only **账号线程占用** in ServerBox's custom-command editor.
The GPU command and SSH connection are independent.

## Independent metric card

The local client promotes this command to an independent metric row beside
CPU, network speed and traffic. It uses the same `MetricRow` on wide windows
and `ServerDetailMetricTile` on narrow windows. The row opens the complete
output, shows the last successful reading time when disconnected, and can be
hidden independently under server detail cards. The command is excluded from
the generic custom-command group so it is not displayed twice; the H100
command remains there.

`lib/view/page/server/detail/account_threads_card.dart` displays the sampler's
first two lines as text; it does not infer a common quota or an occupancy
percentage. Empty or excessively long output stays available in the detail
without being rendered as zero or overflowing the row.

The local variant uses `SERVERBOX_DATA_NAME=ServerBoxH100` to isolate its
working directory from the stock app. Its application identifier is
`local.ferry.serverbox.h100`. A local ad-hoc signature cannot claim the
restricted application-identifier entitlement needed by the data-protection
keychain, so this variant uses a separate service in the macOS system login
keychain. The fl_lib build flags are:

```
FL_LIB_MACOS_DATA_PROTECTION_KEYCHAIN=false
FL_LIB_MACOS_SECURE_ACCOUNT=local.ferry.serverbox.h100
```

The defaults remain the original data-protection keychain and service; these
flags do not read or migrate the original app's secrets. The local variant
imports the authorized SSH key **path**, not its private bytes into this repo.

The UI uses Flutter 3.47.5, engine `af7e796e161ae0bb1ff0758c71a7105418bd9ded`,
matching the installed 1.0.1816 client. The Dart AOT framework is compiled via
the SDK's `CompileMacOSFramework` target and packaged with the existing native
frameworks and Runner. The full native Runner/Rust workspace is not rebuilt.
Do not reuse that runtime across a change to the FFI or native plugin API.
The full SDK Material font is bundled so the thread icon is present.

## Verification

```sh
python3 -m unittest discover -s scripts/thread-monitor -v
```

Fixtures cover UID filtering, real thread sums, grouping, inherited limit
sources, process exit races, unavailable procfs and the scan deadline.

UI verification covers wide/narrow layout, tapping to open details, a changed
poll value, stale timestamps, empty output and long errors. The four card
tests and six existing readout tests passed using Flutter's test runner with
native build hooks omitted: these tests do not call FFI. Static analysis of
the changed app files also passed. Native libraries are reused only for the
local UI build, with live connection verification required separately.

The matching SDK driver is saved as `ui_tools.dart.template` (copy it to a
temporary `.dart` file and run it with the SDK's flutter_tools package
configuration). It exposes the SDK's AOT framework target without rebuilding
unchanged native dependencies, and the normal Flutter UI test command without
native build hooks. Set `FLUTTER_ROOT` to the matching SDK. For this SDK's
low-level `assemble` command, pass the three local-variant defines above as
separate Base64-encoded `--dart-define` values. The Dart AOT output replaces
only the copied App framework; retain the matching native-assets manifest and
re-sign the local copy with unrestricted development entitlements.

The installed local variant is `~/Applications/ServerBox H100.app`. It was
restarted and automatically reconnected on 2026-10-23. At 20:08 Beijing its
independent card showed 429 threads in 90 processes; the H100 card also resumed
live readings. The sampling interval is five seconds and the retry limit is
zero (unlimited). No original client database or original keychain entry was
imported or overwritten. Connection trust was verified against the existing
CLI's known-host fingerprint before accepting it in the local client.
