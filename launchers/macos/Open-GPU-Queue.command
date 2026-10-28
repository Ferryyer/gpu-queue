#!/bin/bash
# macOS Finder launcher. Uses only the owner's existing SSH configuration.
set -u
umask 077
ssh_bin="${GPUQ_SSH_BIN:-/usr/bin/ssh}"
curl_bin="${GPUQ_CURL_BIN:-/usr/bin/curl}"
open_bin="${GPUQ_OPEN_BIN:-/usr/bin/open}"
dialog_bin="${GPUQ_DIALOG_BIN:-/usr/bin/osascript}"
state_dir="${GPUQ_LAUNCHER_STATE_DIR:-$HOME/Library/Application Support/GPU Queue}"
ssh_host="${GPUQ_SSH_HOST:-markflow-cpu}"
remote_socket='/tmp/gpuq-21005/web.sock'
ssh_pid=''
lock_owned=0
mkdir -p "$state_dir" || exit 1
chmod 700 "$state_dir"
log_file="$state_dir/connection.log"
lock_dir="$state_dir/connecting"

cleanup() {
    if [ -n "$ssh_pid" ]; then
        kill "$ssh_pid" 2>/dev/null || true
        wait "$ssh_pid" 2>/dev/null || true
    fi
    if [ "$lock_owned" = 1 ]; then
        rm -f "$lock_dir/pid"
        rmdir "$lock_dir" 2>/dev/null || true
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
fail() {
    printf '\n%s\n' "$1"
    if [ -t 0 ]; then
        printf '按回车关闭窗口。'
        read -r answer || true
    fi
    exit 1
}
ready() {
    local body
    body=$("$curl_bin" --noproxy '*' --connect-timeout 1 --max-time 2 --fail --silent "http://127.0.0.1:$1/api/health" 2>/dev/null) || return 1
    case "$body" in *'"service":"gpuq"'*) ;; *) return 1 ;; esac
    case "$body" in *'"owner":"linlishuo"'*) ;; *) return 1 ;; esac
    case "$body" in *'"uid":21005'*) ;; *) return 1 ;; esac
}
open_page() {
    "$open_bin" "http://127.0.0.1:$1/" || fail '连接正常，但浏览器未能自动打开。请访问上方本地地址。'
}
existing_page() {
    local candidate saved
    saved=''
    if [ -f "$state_dir/port" ]; then saved=$(cat "$state_dir/port"); fi
    case "$saved" in 879[0-9]) ;; *) saved='' ;; esac
    for candidate in "$saved" 8790 8791 8792 8793 8794 8795 8796 8797 8798 8799; do
        [ -n "$candidate" ] || continue
        if ready "$candidate"; then
            printf '连接已就绪，正在打开 Inspire Queue。\n'
            open_page "$candidate"
            return 0
        fi
    done
    return 1
}
existing_page && exit 0
# Serialize connection setup across simultaneous double-clicks. No shared keys.
if ! mkdir "$lock_dir" 2>/dev/null; then
    old_pid=''
    if [ -f "$lock_dir/pid" ]; then old_pid=$(cat "$lock_dir/pid"); fi
    case "$old_pid" in ''|*[!0-9]*) old_pid='' ;; esac
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
        printf '另一个启动窗口正在连接，稍等即可。\n'
        for ((attempt=0; attempt<90; attempt++)); do
            existing_page && exit 0
            kill -0 "$old_pid" 2>/dev/null || break
            sleep 1
        done
        fail '另一窗口尚未完成登录，请查看那个连接窗口。'
    fi
    rm -f "$lock_dir/pid"
    rmdir "$lock_dir" 2>/dev/null || fail '启动器状态无法更新，请关闭其他启动窗口后再试。'
    mkdir "$lock_dir" || fail '连接正在建立，请稍后再打开。'
fi
lock_owned=1
printf '%s\n' "$$" > "$lock_dir/pid"

config=''
valid_config() {
    local hostname
    [ -f "$1" ] || return 1
    # A chosen config must never be mistaken for a private key.
    if /usr/bin/grep -q 'PRIVATE KEY' "$1"; then return 1; fi
    hostname=$("$ssh_bin" -G -F "$1" "$ssh_host" 2>/dev/null | /usr/bin/awk '$1=="hostname" {print $2; exit}')
    [ -n "$hostname" ] && [ "$hostname" != "$ssh_host" ]
}
saved_config=''
if [ -f "$state_dir/ssh-config-path" ]; then saved_config=$(cat "$state_dir/ssh-config-path"); fi
for candidate in "${GPUQ_SSH_CONFIG:-}" "$saved_config" "$HOME/.ssh/markflow-linlishuo/config" "$HOME/.ssh/config"; do
    [ -n "$candidate" ] || continue
    if valid_config "$candidate"; then config="$candidate"; break; fi
done
if [ -z "$config" ]; then
    printf '请选择你原来登录服务器使用的 SSH 配置文件。\n'
    config=$("$dialog_bin" <<'APPLESCRIPT'
set selectedConfig to choose file with prompt "选择你已有的服务器 SSH 配置文件（config）" with invisibles
POSIX path of selectedConfig
APPLESCRIPT
    ) || fail '尚未选择 SSH 配置，下次双击可重新选择。'
    valid_config "$config" || fail '这个文件中没有可用的 markflow-cpu 配置，请选择你原来的成员 SSH 配置。'
fi
printf '%s\n' "$config" > "$state_dir/ssh-config-path"
printf '正在连接你的服务器。首次使用时，请按提示完成原有 SSH 登录。\n'
connected_port=''
for port in 8790 8791 8792 8793 8794 8795 8796 8797 8798 8799; do
    if ready "$port"; then open_page "$port"; exit 0; fi
    : > "$log_file"
    "$ssh_bin" -F "$config" -N -T -o ExitOnForwardFailure=yes -o ConnectTimeout=15 -o ServerAliveInterval=20 -o ServerAliveCountMax=3 -L "127.0.0.1:$port:$remote_socket" "$ssh_host" 2> "$log_file" &
    ssh_pid=$!
    port_busy=0
    for ((attempt=0; attempt<180; attempt++)); do
        if ! kill -0 "$ssh_pid" 2>/dev/null; then
            wait "$ssh_pid" 2>/dev/null || true
            ssh_pid=''
            if /usr/bin/grep -Eq 'Address already in use|cannot listen to port|Could not request local forwarding' "$log_file"; then
                port_busy=1
                break
            fi
            cat "$log_file"
            fail 'SSH 连接未成功。请检查网络和原有的服务器登录方式，再双击重试。'
        fi
        if ready "$port"; then connected_port="$port"; break; fi
        sleep 1
    done
    [ -n "$connected_port" ] && break
    [ "$port_busy" = 1 ] && continue
    fail 'SSH 已连接，但网页暂时没有响应。请稍后双击重试；服务器上的任务会继续执行。'
done
[ -n "$connected_port" ] || fail '本地 8790–8799 端口都已被占用，请关闭自己不用的连接窗口后重试。'
printf '%s\n' "$connected_port" > "$state_dir/port"
printf '\n已连接：http://127.0.0.1:%s/\n' "$connected_port"
open_page "$connected_port"
printf '\n保持此窗口打开即可使用网页；关闭窗口不会停止服务器上已经启动的任务。\n'
rm -f "$lock_dir/pid"
rmdir "$lock_dir" 2>/dev/null || true
lock_owned=0
wait "$ssh_pid"
ssh_result=$?
ssh_pid=''
[ "$ssh_result" = 0 ] || fail '连接已断开。需要查看网页时，再双击启动器即可。'
