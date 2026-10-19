#!/usr/bin/env bash
# Verifies a running browser-desktop container end to end:
# healthy, CDP up, landscape/portrait pixels, transparent cursors and Unicode input,
# session reuse, and the browser surviving viewer disconnects.
# Usage: verify.sh <container> <rdp-host> <rdp-port> <cdp-port> <password-file>
set -euo pipefail
container=$1 rdp_host=$2 rdp_port=$3 cdp_port=$4 password_file=$5
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
umask 077
evidence="${VERIFY_EVIDENCE:?set VERIFY_EVIDENCE to a private directory outside the repository}"
mkdir -p "$evidence"
evidence="$(readlink -f "$evidence")"
fail() { echo "FAIL: $*" >&2; exit 1; }
in_box() { sudo -n docker exec "$container" "$@"; }
cleanup() {
    result=$?
    trap - EXIT
    if (( result != 0 )); then
        bash "$HERE/../diagnose.sh" "$container" "$evidence/failure" \
            || echo 'Diagnostic snapshot failed; preserving the original test failure' >&2
    fi
    if [[ -f "$evidence/target.json" ]]; then
        if ! node "$HERE/visual-target.mjs" close "$cdp_port" "$evidence/target.json"; then
            echo "FAIL: could not close the synthetic test tab" >&2
            result=1
        fi
    fi
    if [[ -f "$evidence/unicode-target.json" ]]; then
        if ! node "$HERE/unicode-target.mjs" close "$cdp_port" "$evidence/unicode-target.json"; then
            echo "FAIL: could not close the synthetic Unicode tab" >&2
            result=1
        fi
    fi
    if [[ -f "$evidence/rotation-target.json" ]]; then
        if ! node "$HERE/rotation-target.mjs" close "$cdp_port" "$evidence/rotation-target.json"; then
            echo "FAIL: could not close the synthetic rotation tab" >&2
            result=1
        fi
    fi
    exit "$result"
}
trap cleanup EXIT

health="$(sudo -n docker inspect -f '{{.State.Health.Status}}' "$container")"
[[ "$health" == healthy ]] || fail "container health is $health"
curl -fsS "http://127.0.0.1:${cdp_port}/json/version" >/dev/null || fail "CDP not reachable on ${cdp_port}"
if [[ "$(in_box printenv BROWSER_EXECUTABLE)" == /usr/bin/google-chrome-stable ]]; then
    node "$HERE/sandbox.mjs" "$cdp_port" "$evidence/sandbox.json" \
        || fail 'Chrome sandbox is disabled'
fi
cursor_style="$(in_box printenv CURSOR_STYLE)"
desktop_user="$(in_box printenv DESKTOP_USER || echo browser)"
case "$cursor_style" in
    arrow) expected_link_cursor=arrow ;;
    native) expected_link_cursor=hand ;;
    *) fail "unknown CURSOR_STYLE" ;;
esac

display_before="$(in_box grep '^DISPLAY=' /run/browser-desktop/session)"
browser_before="$(in_box pgrep -o -x 'chromium|chrome')"
xorg_before="$(in_box pgrep -o -x Xorg)"
session_before="$(in_box pgrep -o -x xrdp-sesexec)"
[[ "$(in_box pgrep -c -x Xorg)" == 1 ]] || fail "expected exactly one Xorg before login"

sesman_lines="$(in_box sh -c 'wc -l < /var/log/xrdp-sesman.log')"
xrdp_lines="$(in_box sh -c 'wc -l < /var/log/xrdp.log')"
sudo -n env HTTP_PROXY="${HTTP_PROXY:-}" HTTPS_PROXY="${HTTPS_PROXY:-}" \
    http_proxy="${http_proxy:-}" https_proxy="${https_proxy:-}" \
    docker build --progress plain --network host --build-arg HTTP_PROXY="${HTTP_PROXY:-}" --build-arg HTTPS_PROXY="${HTTPS_PROXY:-}" \
    --build-arg http_proxy="${http_proxy:-}" --build-arg https_proxy="${https_proxy:-}" \
    -t browser-desktop-rdp-client:visual "$HERE/rdp-client" > "$evidence/client-build.log" 2>&1
node "$HERE/visual-target.mjs" open "$cdp_port" "$evidence/target.json"
for phase in 1 2; do
    sudo -n docker run --rm --init --network host \
        -e RDP_USER="$desktop_user" \
        -e EXPECTED_LINK_CURSOR="$expected_link_cursor" \
        -v "$(readlink -f "$password_file"):/pw:ro" -v "$evidence:/evidence" \
        browser-desktop-rdp-client:visual \
        timeout 110 xvfb-run -a -s '-screen 0 1280x1440x24' python3 /visual-client.py "$rdp_host" "$rdp_port" "$phase" \
        > "$evidence/visual-$phase.log" 2>&1 \
        || fail "RDP desktop pixels/input failed on connection $phase; see $evidence"
    cat "$evidence/visual-$phase.log"
done

for codec in basic avc420; do
    node "$HERE/rotation-target.mjs" open "$cdp_port" "$evidence/rotation-target.json"
    mkdir -p "$evidence/rotation-$codec"
    sudo -n docker run --rm --init --network host \
        -e RDP_USER="$desktop_user" \
        -v "$(readlink -f "$password_file"):/pw:ro" -v "$evidence/rotation-$codec:/evidence" \
        browser-desktop-rdp-client:visual \
        timeout 110 xvfb-run -a -s '-screen 0 1440x1500x24' \
        python3 /rotation-client.py "$rdp_host" "$rdp_port" "$codec" \
        > "$evidence/rotation-$codec/result.log" 2>&1 \
        || fail "RDP rotation pixels/input failed; see $evidence/rotation-$codec"
    cat "$evidence/rotation-$codec/result.log"
    node "$HERE/rotation-target.mjs" close "$cdp_port" "$evidence/rotation-target.json"
    rm "$evidence/rotation-target.json"
done

node "$HERE/unicode-target.mjs" open "$cdp_port" "$evidence/unicode-target.json"
sudo -n docker run --rm --init --network host \
    -e RDP_USER="$desktop_user" \
    -e RDP_CHECK_SHORTCUTS="${VERIFY_SHORTCUTS:-0}" \
    -v "$(readlink -f "$password_file"):/pw:ro" -v "$evidence:/evidence" \
    browser-desktop-rdp-client:visual \
    timeout 80 xvfb-run -a -s '-screen 0 1280x800x24' python3 /unicode-input.py "$rdp_host" "$rdp_port" \
    > "$evidence/unicode-client-result.log" 2>&1 || fail "RDP Unicode client failed; see $evidence"
if [[ "${VERIFY_SHORTCUTS:-0}" == 1 ]]; then
    sudo -n docker run --rm --init --network host \
        -e RDP_USER="$desktop_user" -e RDP_NATIVE_SHORTCUTS_ONLY=1 \
        -v "$(readlink -f "$password_file"):/pw:ro" -v "$evidence:/evidence" \
        browser-desktop-rdp-client:visual \
        timeout 80 xvfb-run -a -s '-screen 0 1280x800x24' python3 /unicode-input.py "$rdp_host" "$rdp_port" \
        > "$evidence/native-shortcuts-result.log" 2>&1 || fail "RDP native shortcuts client failed; see $evidence"
fi
node "$HERE/unicode-target.mjs" check "$cdp_port" "$evidence/unicode-target.json" \
    > "$evidence/unicode-value.json" || fail "RDP Unicode text did not reach the input"

in_box tail -n "+$((sesman_lines + 1))" /var/log/xrdp-sesman.log > "$evidence/sesman.log"
in_box tail -n "+$((xrdp_lines + 1))" /var/log/xrdp.log > "$evidence/xrdp.log"
# An owner may reconnect while these clients run. Every observed reconnect must
# use the original session; extra viewers must not turn a successful check red.
python3 -I "$HERE/check-reconnects.py" "$evidence/sesman.log" "$display_before" "$session_before" 5 --user "$desktop_user" \
    || fail "RDP logins did not reattach to the pre-created session"
if grep -Eq 'Error connecting to (X server|Xorg|user session)' "$evidence/xrdp.log"; then
    fail "xrdp reported a desktop connection failure; see $evidence/xrdp.log"
fi
[[ "$(in_box pgrep -c -x Xorg)" == 1 ]] || fail "login created a second Xorg instead of reusing the session"
[[ "$(in_box pgrep -o -x Xorg)" == "$xorg_before" ]] || fail "Xorg restarted during login/disconnect"
[[ "$(in_box grep '^DISPLAY=' /run/browser-desktop/session)" == "$display_before" ]] || fail "session display changed"
[[ "$(in_box pgrep -o -x 'chromium|chrome')" == "$browser_before" ]] || fail "browser restarted during login/disconnect"
curl -fsS "http://127.0.0.1:${cdp_port}/json/version" >/dev/null || fail "CDP lost after disconnect"
echo "OK: landscape/portrait pixels, rotation clicks, transparent cursors and Chinese verified; session reused and browser survived disconnect; evidence $evidence"
