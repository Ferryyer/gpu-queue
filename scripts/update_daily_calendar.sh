#!/bin/bash
# macOS standalone updater. Only Apple-provided tools and the bundled, local
# date verifier are used. No Codex, Python, AI service, or developer account.
set -euo pipefail
umask 077
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
export TZ=Asia/Shanghai
cache=${1:?Usage: update_daily_calendar.sh CACHE_DIR [YYYY-MM-DD] [CalendarCheck]}
day=${2:-$(/bin/date +%F)}
checker=${3:-"$(cd "$(dirname "$0")" && pwd)/CalendarCheck"}
[[ "$day" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || exit 64
[[ "$(/bin/date -j -f '%Y-%m-%d' "$day" +%F 2>/dev/null)" == "$day" ]] || exit 64
[[ -x "$checker" ]] || { echo 'Calendar date verifier is missing' >&2; exit 69; }
/bin/mkdir -p "$cache"
target="$cache/$day.jpg"
if [[ -f "$target" ]] && "$checker" "$target" "$day" >/dev/null; then
    printf '%s\n' "$day"
    exit 0
fi
temp=$(/usr/bin/mktemp -d "$cache/.download.XXXXXX")
trap '/bin/rm -rf "$temp"' EXIT
# The publisher occasionally places a page under the following day's filename.
# Both candidates must pass printed month/day/year verification; never assume
# that a 200 response or a fresh mtime means that the image is today's calendar.
next=$(/bin/date -j -v+1d -f '%Y-%m-%d' "$day" +%F)
for candidate in "$day" "$next"; do
    year=${candidate:0:4}
    month=${candidate:5:2}
    date=${candidate:8:2}
    url="https://img.owspace.com/Public/uploads/Download/$year/$month$date.jpg"
    if ! /usr/bin/curl --fail --silent --show-error --location --max-redirs 2 \
        --proto '=https' --proto-redir '=https' --connect-timeout 10 --max-time 25 \
        --max-filesize 10485760 --output "$temp/image.jpg" "$url"; then
        continue
    fi
    [[ $(/usr/bin/stat -f %z "$temp/image.jpg") -le 10485760 ]] || continue
    if ! "$checker" "$temp/image.jpg" "$day" >/dev/null; then continue; fi
    printf '# 单向历 · %s\n\n图片来源：[单向空间原图](%s)。\n\n图面日期已在本机核对；作者与作品出处见原图署名。\n' "$day" "$url" > "$temp/source.md"
    /bin/mv -f "$temp/source.md" "$cache/$day.md"
    /bin/mv -f "$temp/image.jpg" "$target"
    printf '%s\n' "$day"
    exit 0
done
echo 'No calendar with the requested printed date is available; previous cache preserved' >&2
exit 75
