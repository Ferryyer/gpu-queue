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
        --header 'Cache-Control: no-cache' --header 'Pragma: no-cache' \
        --max-filesize 10485760 --output "$temp/image.jpg" \
        "$url?inspire_calendar_check=${temp##*/}-$RANDOM"; then
        continue
    fi
    [[ $(/usr/bin/stat -f %z "$temp/image.jpg") -le 10485760 ]] || continue
    if ! "$checker" "$temp/image.jpg" "$day" >/dev/null; then continue; fi
    # A single atomic manifest publishes the verified bytes AND their source.
    # Readers of the previous manifest retain an immutable, checksummed image.
    digest=$(/usr/bin/shasum -a 256 "$temp/image.jpg")
    digest=${digest%% *}
    [[ "$digest" =~ ^[a-f0-9]{64}$ ]] || exit 65
    /bin/mv -f "$temp/image.jpg" "$cache/$day.$digest.jpg"
    printf '{"date":"%s","sha256":"%s","source":"%s"}\n' "$day" "$digest" "$url" > "$temp/manifest.json"
    /bin/mv -f "$temp/manifest.json" "$cache/$day.json"
    printf '%s\n' "$day"
    exit 0
done
echo 'No calendar with the requested printed date is available; previous cache preserved' >&2
exit 75
