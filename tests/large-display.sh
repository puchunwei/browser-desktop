#!/usr/bin/env bash
# Real decoded pixels/input on a disposable server only. Never use a personal profile.
set -euo pipefail
[[ ${VERIFY_DISPOSABLE:-0} == 1 ]] || { echo 'Set VERIFY_DISPOSABLE=1 for an isolated test instance' >&2; exit 2; }
HERE=$(cd -- "$(dirname -- "$0")" && pwd)
container=${1:?container}
rdp_host=${2:?rdp host}
rdp_port=${3:?rdp port}
cdp_port=${4:?CDP port}
password_file=${5:?synthetic password file}
evidence=${6:?evidence directory}
read -r -a docker <<< "${DOCKER:-docker}"
client_image=${RDP_CLIENT_IMAGE:-browser-desktop-rdp-client:visual}
[[ $("${docker[@]}" inspect -f '{{index .Config.Labels "browser-desktop.test"}}' "$container") == large-display ]] \
    || { echo 'Container must have label browser-desktop.test=large-display' >&2; exit 2; }
original_compression=$("${docker[@]}" exec "$container" sed -n 's/^bitmap_compression=//p' /etc/xrdp/xrdp.ini)
[[ $original_compression == true || $original_compression == false ]] || exit 2
mkdir -p "$evidence"
evidence=$(cd "$evidence" && pwd)
cleanup() {
    "${docker[@]}" exec "$container" sed -i "s/^bitmap_compression=.*/bitmap_compression=$original_compression/" /etc/xrdp/xrdp.ini
    node "$HERE/rotation-target.mjs" close "$cdp_port" "$evidence/target.json"
}
node "$HERE/rotation-target.mjs" open "$cdp_port" "$evidence/target.json" --maximize
trap cleanup EXIT
for mode in compressed uncompressed; do
    enabled=true
    [[ $mode == compressed ]] || enabled=false
    # xrdp reads this setting for each new connection. FreeRDP's -compression
    # controls bulk compression and does not select uncompressed bitmap updates.
    "${docker[@]}" exec "$container" sed -i "s/^bitmap_compression=.*/bitmap_compression=$enabled/" /etc/xrdp/xrdp.ini
    for size in 1280x720 3840x2160 4096x2160 6016x3384 8192x2160; do
        phase="$evidence/$mode-$size"
        mkdir -p "$phase"
        before=$("${docker[@]}" exec "$container" wc -l /var/log/xrdp.log | awk '{print $1}')
        "${docker[@]}" run --rm --init --network host \
            -v "$(readlink -f "$password_file"):/pw:ro" -v "$phase:/evidence" \
            -v "$HERE/rdp-client/large-display.py:/large-display.py:ro" \
            "$client_image" timeout 110 xvfb-run -a -s "-screen 0 ${size}x24" \
            python3 /large-display.py "$rdp_host" "$rdp_port" "$size" \
            > "$phase/result.log" 2>&1 || {
                cat "$phase/result.log" >&2
                tail -n 12 "$phase/freerdp.log" >&2 || true
                exit 1
            }
        cat "$phase/result.log"
        "${docker[@]}" exec "$container" tail -n "+$((before+1))" /var/log/xrdp.log > "$phase/server.log"
        if grep -Eq 'starting gfx|decompressed size too big|compressed size too big|lines_sending == zero' "$phase/server.log"; then
            echo "Wrong codec or oversized bitmap in $phase/server.log" >&2
            exit 1
        fi
    done
done
echo 'PASS: legacy desktop colors and real clicks at 1280, 3840, 4096, 6016 and 8192 pixels, with and without compression'
