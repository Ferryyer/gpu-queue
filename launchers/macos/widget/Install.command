#!/bin/bash
# Install a native JXA/AppKit desktop panel using macOS built-in tools.
set -eu
umask 077
source_dir=$(cd "$(dirname "$0")" && pwd)
apps_dir="$HOME/Applications"
state_dir="$HOME/Library/Application Support/GPU Queue"
app_name='GPU 任务台小组件.app'
mode=${1:-install}
case "$mode" in install|--update) ;; *) printf '安装参数无效。\n'; exit 1 ;; esac
compile_bin=${GPUQ_OSACOMPILE_BIN:-/usr/bin/osacompile}
plistbuddy_bin=${GPUQ_PLISTBUDDY_BIN:-/usr/libexec/PlistBuddy}
codesign_bin=${GPUQ_CODESIGN_BIN:-/usr/bin/codesign}
open_bin=${GPUQ_OPEN_BIN:-/usr/bin/open}
osascript_bin=${GPUQ_OSASCRIPT_BIN:-/usr/bin/osascript}
move_bin=${GPUQ_MOVE_BIN:-/bin/mv}
[ -x "$compile_bin" ] || { printf '需要在 Mac 上运行此安装器。\n'; exit 1; }
version=$(cat "$source_dir/VERSION")
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { printf '安装包版本无效。\n'; exit 1; }
mkdir -p "$apps_dir" "$state_dir"
chmod 700 "$state_dir"
work_dir=$(mktemp -d "$apps_dir/.gpuq-widget.XXXXXX")
installed="$apps_dir/$app_name"
backup=''; replaced=0; complete=0
cleanup() {
    code=$?
    trap - EXIT
    # Compilation happens before replacement. Roll back a failed update swap.
    if [ "$complete" = 0 ] && [ -n "$backup" ] && [ -d "$backup" ]; then
        if [ "$replaced" = 1 ] && [ -d "$installed" ]; then /bin/mv "$installed" "$work_dir/failed.app"; fi
        if [ ! -e "$installed" ]; then /bin/mv "$backup" "$installed"; fi
    fi
    rm -rf "$work_dir"
    exit "$code"
}
trap cleanup EXIT
trap 'exit 143' TERM HUP
trap 'exit 130' INT
if [ -L "$installed" ]; then printf '目标应用是符号链接，未覆盖。\n'; exit 1; fi
if [ -e "$installed" ]; then
    existing=$("$plistbuddy_bin" -c 'Print :CFBundleIdentifier' "$installed/Contents/Info.plist" 2>/dev/null || true)
    [ "$existing" = work.markflow.gpuqueue.widget.linlishuo ] || { printf '目标位置已有其他应用，未覆盖：%s\n' "$installed"; exit 1; }
fi
if [ "$mode" = --update ]; then
    handoff=${2:-}
    [ -d "$installed" ] && [ -d "$handoff" ] && [ ! -L "$handoff" ] && [ -O "$handoff" ] || { printf '更新会话无效。\n'; exit 1; }
    handoff=$(cd "$handoff" && pwd -P)
    canonical_state=$(cd "$state_dir" && pwd -P)
    [ "$(dirname "$handoff")" = "$canonical_state" ] && [[ "$(basename "$handoff")" =~ ^update-[A-Za-z0-9-]+$ ]] || { printf '更新目录无效。\n'; exit 1; }
    [ ! -e "$handoff/ready" ] && [ ! -e "$handoff/continue" ] || { printf '更新会话已经使用，请重新检查更新。\n'; exit 1; }
fi
app="$work_dir/$app_name"
printf '正在安装 GPU 任务台桌面小组件 %s…\n' "$version"
"$compile_bin" -s -l JavaScript -o "$app" "$source_dir/Widget.bundle.js"
/bin/cp "$source_dir/Open-GPU-Queue.command" "$app/Contents/Resources/Open-GPU-Queue.command"
/bin/chmod 755 "$app/Contents/Resources/Open-GPU-Queue.command"
helper="$app/Contents/Helpers/GPU 任务台更新器.app"
mkdir -p "$(dirname "$helper")"
"$compile_bin" -s -l JavaScript -o "$helper" "$source_dir/Updater.bundle.js"
set_plist() {
    "$plistbuddy_bin" -c "Set :$2 $4" "$1" 2>/dev/null || "$plistbuddy_bin" -c "Add :$2 $3 $4" "$1"
}
for bundle in "$app" "$helper"; do
    plist="$bundle/Contents/Info.plist"
    if [ "$bundle" = "$app" ]; then bundle_id=work.markflow.gpuqueue.widget.linlishuo; else bundle_id=work.markflow.gpuqueue.widget.linlishuo.updater; fi
    set_plist "$plist" CFBundleIdentifier string "$bundle_id"
    set_plist "$plist" CFBundleShortVersionString string "$version"
    set_plist "$plist" CFBundleVersion string "$version"
    set_plist "$plist" LSUIElement bool true
    set_plist "$plist" NSHighResolutionCapable bool true
    set_plist "$plist" LSMinimumSystemVersion string 10.13
done
# Sign the locally generated app after updating its own resources and metadata.
"$codesign_bin" --force --sign - "$helper"
"$codesign_bin" --force --sign - "$app"
"$codesign_bin" --verify --deep --strict "$app"
if [ "$mode" = --update ]; then
    # The separate updater asks the old panel to quit only after compilation.
    : > "$handoff/ready"
    attempts=0
    while [ ! -f "$handoff/continue" ]; do
        attempts=$((attempts+1))
        [ "$attempts" -lt 300 ] || { printf '等待关闭旧版超时，未替换应用。\n'; exit 1; }
        sleep .2
    done
else
    # Also handle the first upgrade from versions without an updater button.
    "$osascript_bin" -l JavaScript - "$installed" <<'JXA'
ObjC.import('AppKit');
function run(args) {
    var apps = $.NSRunningApplication.runningApplicationsWithBundleIdentifier('work.markflow.gpuqueue.widget.linlishuo');
    var pending = [];
    for (var i = 0; i < apps.count; i++) {
        var candidate = apps.objectAtIndex(i);
        if (ObjC.unwrap(candidate.bundleURL.path) === args[0] && !candidate.terminated) {
            pending.push(candidate); candidate.terminate;
        }
    }
    for (var tries = 0; tries < 150 && pending.some(function (p) { return !p.terminated; }); tries++) {
        $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(.2));
    }
    if (pending.some(function (p) { return !p.terminated; })) throw new Error('请先关闭旧版小组件，再运行安装器。');
}
JXA
fi
if [ -e "$installed" ]; then
    backup="$apps_dir/GPU 任务台小组件.previous-$(date +%Y%m%d%H%M%S)-$$.app"
    "$move_bin" "$installed" "$backup"
fi
"$move_bin" "$app" "$installed"
replaced=1
# This is a link to this app; existing unrelated desktop files are never replaced.
if [ -d "$HOME/Desktop" ] && [ ! -e "$HOME/Desktop/$app_name" ] && [ ! -L "$HOME/Desktop/$app_name" ]; then
    /bin/ln -s "$installed" "$HOME/Desktop/$app_name"
fi
printf '\n已安装：%s\n桌面上已有入口，可拖动面板或勾选置顶。\n' "$installed"
if [ "$mode" = --update ]; then
    # Login preference and SSH settings are untouched by in-app updates.
    "$open_bin" -n "$installed"
    complete=1
    exit 0
fi
complete=1
# Registering the RunAtLoad item also opens the installed app for this login.
if ! /bin/bash "$source_dir/Autostart.command" enable; then
    printf '小组件已安装，自启动尚未启用。\n'
    /usr/bin/open "$installed"
    exit 1
fi
