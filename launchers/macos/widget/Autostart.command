#!/bin/bash
# A per-user login launcher. It opens the panel once; it never supervises it.
set -eu
umask 077
action=${1:-enable}
case "$action" in enable|disable) ;; *) printf '未知操作：%s\n' "$action"; exit 1 ;; esac
launchctl_bin=${GPUQ_LAUNCHCTL_BIN:-/bin/launchctl}
plutil_bin=${GPUQ_PLUTIL_BIN:-/usr/bin/plutil}
plistbuddy_bin=${GPUQ_PLISTBUDDY_BIN:-/usr/libexec/PlistBuddy}
[ -x "$launchctl_bin" ] && [ -x "$plutil_bin" ] && [ -x "$plistbuddy_bin" ] || {
    printf '请在 Mac 上运行此工具。\n'; exit 1;
}
label='work.markflow.gpuqueue.widget.linlishuo.autostart'
domain="gui/$(id -u)"
target="$domain/$label"
agent_dir="$HOME/Library/LaunchAgents"
plist="$agent_dir/$label.plist"
installed="$HOME/Applications/GPU 任务台小组件.app"

# Never follow or replace an unrelated login item.
if [ -L "$plist" ]; then
    printf '登录项路径是符号链接，未修改：%s\n' "$plist"; exit 1
fi
if [ -e "$plist" ]; then
    existing=$("$plistbuddy_bin" -c 'Print :Label' "$plist" 2>/dev/null || true)
    [ "$existing" = "$label" ] || { printf '已有其他登录项，未修改：%s\n' "$plist"; exit 1; }
fi

unload_own_item() {
    if "$launchctl_bin" print "$target" >/dev/null 2>&1; then
        "$launchctl_bin" bootout "$target" || {
            printf '无法更新当前登录项，未报告成功。\n'; return 1;
        }
    fi
}

if [ "$action" = disable ]; then
    unload_own_item
    /bin/rm -f "$plist"
    printf '\n已关闭开机自启动。下次登录 Mac 不再自动打开小面板。\n当前面板和服务器任务继续运行。\n'
    exit 0
fi

[ -d "$installed" ] || { printf '请先双击“安装桌面小组件.command”，再开启自启动。\n'; exit 1; }
bundle_id=$("$plistbuddy_bin" -c 'Print :CFBundleIdentifier' "$installed/Contents/Info.plist" 2>/dev/null || true)
[ "$bundle_id" = work.markflow.gpuqueue.widget.linlishuo ] || {
    printf '目标应用身份不符，未设置自启动：%s\n' "$installed"; exit 1;
}
"$launchctl_bin" print "$domain" >/dev/null 2>&1 || {
    printf '请登录 Mac 桌面后，双击“开启开机自启动.command”。\n'; exit 1;
}
mkdir -p "$agent_dir"
temporary=$(mktemp "$agent_dir/.gpuq-autostart.XXXXXX")
trap 'rm -f "$temporary"' EXIT
escaped_app=$(printf '%s' "$installed" | /usr/bin/sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/"/\&quot;/g' -e "s/'/\&apos;/g")
cat > "$temporary" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>Label</key><string>$label</string>
    <key>ProgramArguments</key><array>
        <string>/usr/bin/open</string><string>-g</string><string>$escaped_app</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>LimitLoadToSessionType</key><string>Aqua</string>
</dict></plist>
EOF
"$plutil_bin" -lint "$temporary" >/dev/null
unload_own_item
/bin/mv "$temporary" "$plist"
if ! "$launchctl_bin" enable "$target" || ! "$launchctl_bin" bootstrap "$domain" "$plist"; then
    printf '登录项文件已保存，但系统未成功启用。请在 Mac 桌面重新运行“开启开机自启动.command”。\n'
    exit 1
fi
"$launchctl_bin" print "$target" >/dev/null || {
    printf '未能确认自启动已启用，请重试。\n'; exit 1;
}
printf '\n已开启开机自启动：登录 Mac 后自动打开 GPU 任务台小面板。\n关闭请双击同一文件夹中的“关闭开机自启动.command”。\n'
