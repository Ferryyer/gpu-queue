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
temp=$(/usr/bin/mktemp -d "$cache/.download.XXXXXX")
bundle=''
trap '/bin/rm -rf "$temp"; if [[ -n "$bundle" ]]; then /bin/rm -rf "$bundle"; fi' EXIT
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
        --header 'Cache-Control: no-cache' --header 'Pragma: no-cache' \
        --max-filesize 10485760 --output "$temp/image.jpg" "$url?inspire_refresh=${temp##*.}.$$"; then
        continue
    fi
    [[ $(/usr/bin/stat -f %z "$temp/image.jpg") -le 10485760 ]] || continue
    if ! "$checker" "$temp/image.jpg" "$day" >/dev/null; then continue; fi
    printf '# 单向历 · %s\n\n图片来源：[单向空间原图](%s)。\n\n图面日期已在本机核对；作者与作品出处见原图署名。\n' "$day" "$url" > "$temp/source.md"
    # Image and provenance form one immutable revision. Readers switch both
    # through a single atomic pointer, including same-day corrections.
    current=''
    if [[ -f "$cache/$day.current" ]]; then current=$(/bin/cat "$cache/$day.current"); fi
    if [[ "$current" =~ ^snapshot-$day\.[a-zA-Z0-9]+$ ]] && \
        /usr/bin/cmp -s "$temp/image.jpg" "$cache/$current/image.jpg" && \
        /usr/bin/cmp -s "$temp/source.md" "$cache/$current/source.md"; then
        printf '%s\n' "$day"
        exit 0
    fi
    bundle=$(/usr/bin/mktemp -d "$cache/snapshot-$day.XXXXXX")
    /bin/mv "$temp/image.jpg" "$temp/source.md" "$bundle/"
    revision=${bundle##*/}
    # Keep the pointer temporary in the same filesystem as its destination.
    printf '%s\n' "$revision" > "$temp/current"
    /bin/mv -f "$temp/current" "$cache/$day.current"
    bundle=''
    printf '%s\n' "$day"
    exit 0
done
echo 'No calendar with the requested printed date is available; previous cache preserved' >&2
exit 75
