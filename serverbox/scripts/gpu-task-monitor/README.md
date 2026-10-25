# H100 GPU task monitoring for ServerBox

This integration displays GPU measurements collected in an offline GPU task
alongside the CPU gateway's ordinary metrics. The GPU is labelled `[GPU task]`
to distinguish it from a device attached to the CPU gateway.

## Data flow

1. A foreground `telemetry.py collect` task runs read-only `nvidia-smi` queries
   every five seconds on the existing GPU allocation.
2. It atomically writes a private snapshot to
   `~/.local/state/serverbox-gpu/<request>/latest.json` in the shared HOME.
3. The CPU-side `serverbox-gpu-status xml` helper translates fresh snapshots
   into the XML format already understood by ServerBox's NVIDIA parser.
4. ServerBox reads this through its normal SSH status script. A custom status
   command displays the Beijing sampling time and the request prefix.

No GPU is allocated by these scripts. They do not change clocks, power limits,
drivers, model jobs or the real `nvidia-smi`. They do not expose a web port or
send telemetry to a third-party service. The existing Mac SSH tunnel listens
only on `127.0.0.1:22224`.

## Source changes and current deployment

- `crates/sbm_parser/src/commands.rs`: opt-in private helper fallback after the
  normal NVIDIA and WSL probes.
- `lib/data/model/app/scripts/script_consts.dart`: script version 87 → 88 so a
  future rebuilt client installs the changed script.
- `telemetry.py`: sampler, timestamp checks and XML bridge; Python standard
  library only.
- `patch_probe.py`: applies the same command change to the current signed
  client's generated remote script. It keeps a `.before-gpu-monitor` backup,
  checks file ownership, skips symlinks and replaces the script atomically.
- Custom command `H100 采集状态`: runs the idempotent adapter followed by the
  status helper. This reapplies the fallback after a reconnect regenerates
  the script. A fresh client can need one extra refresh before its GPU card
  appears.

The custom-command filename is `09000_` followed by the **padded** URL-safe
Base64 encoding of its UTF-8 name. Keep trailing `=` characters; ServerBox's
marker decoder requires them. Its file contents are:

```sh
/usr/bin/python3 "$HOME/code/gpu-monitor/patch_probe.py"
"$HOME/.local/bin/serverbox-gpu-status" status
```

## Freshness and lifecycle

### Automatic personal GPU queue integration (2026-10-23)

The personal queue at `~/code/gpu-queue-prototype-20261022` now publishes
`~/.local/state/serverbox-gpu/registry.json` with `schema: 1`, `source: gpuq`
and a `resources` array. Each row carries its request UUID, platform status,
GPU-side `collected_at`, sanitized `gpus`, host and pending-release flag.
The helper prefers this registry whenever it exists. It automatically selects
a fresh online allocation; a late closure of an old allocation cannot hide a
new online one. Closed or failed allocations never emit GPU XML. A corrupt
registry cannot resurrect legacy collector data.

This path reuses the queue's existing short read-only probes, extended with
temperature and the actual GPU sampling time. It does not submit an additional
long-running collector. Normal updates arrive about every 30–45 seconds;
queue samples expire after 90 seconds. CPU registry updates preserve the GPU
timestamp. The older standalone collector below retains its 20-second limit.

Resource checks continue after compute finishes. Confirmed platform closure
is reflected after the queue's notification check (normally within 60 seconds,
plus platform/network delay). Unknown and expired results remain unavailable;
they are never treated as confirmed destruction. Pending release intents are
labelled as unconfirmed; the platform still has no member release API.

The existing ServerBox connection and private SSH key path
stay valid across allocations. Its name is a saved label; the GPU product name
comes from each new instance. For lifecycle troubleshooting, inspect the
registry and `~/.local/state/markflow-services/gpuq.log` on the CPU gateway.

Samples older than 20 seconds, stopped collectors, missing samples, query
failures and invalid timestamps produce no GPU XML. The status command says
`已停止或数据过期`; an unavailable value is never converted into zero.
The CPU's normal monitoring continues independently.

The foreground collector is bounded to 64800 seconds (18 hours), stops after
three consecutive GPU-query failures, and can be stopped using a file in its
request directory. It is submitted once; it never restarts itself, requests
new GPUs or keeps a GPU busy to prevent reclamation. One monitor occupies
one of the request's four task slots.

For a future GPU allocation, submit a new collector explicitly, substituting
the real request UUID. Existing model tasks do not need to be restarted:

```sh
mf-gpu submit --cwd "$HOME/code/gpu-monitor" REQUEST_UUID -- \
  /usr/bin/python3 "$HOME/code/gpu-monitor/telemetry.py" collect \
  --request REQUEST_UUID --seconds 64800 --interval 5
```

Check an existing request's `submission.json` and `collector.lock` before
resubmission. An unclaimed queued job is not proof that a GPU is online.
To stop a standalone collector without affecting model jobs, create the stop
file for its request on the CPU gateway:

```sh
touch "$HOME/.local/state/serverbox-gpu/REQUEST_UUID/stop"
```

## Verify or modify

```sh
python3 -m unittest discover -s scripts/gpu-task-monitor -p 'test_*.py' -v
```

The tests cover metric/units conversion, unsupported readings, freshness,
atomic private writes, real-NVIDIA priority, source/deployment command parity,
idempotent patching and backup preservation. The deployment must also be
verified against a current H100 snapshot and the live ServerBox GPU card.

For rollback, stop the collector, remove only the `H100 采集状态` custom command,
and restore owned status scripts from their `.before-gpu-monitor` backups.
The next stock-client reconnect will also regenerate its original probe.
Remove the helper symlink only after disabling the custom command. ServerBox
credentials are managed separately through its own interface.

### Query recovery changes prepared on 2026-10-23

The queue now reports a `monitor` object with retry/waiting/reconciling or
sampling state. The bridge displays that state on stale/unavailable samples;
a fresh sample still wins, and confirmed closure always wins over retries.
The producer retries failed diagnostics on the same allocation with 5–120
second backoff and archives completed probe specs out of mf-gpu's first-100
input window while preserving their logs and receipts.

The queue-side recovery changes passed 47 local tests and the bridge passed
14 tests. The last activation attempt was blocked by shared-filesystem I/O
waits. Publishing this source does not activate those changes on a server.
Deploy the matching producer in the GPU console separately after its storage
is healthy, preserving any newer console changes.
