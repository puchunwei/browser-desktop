#!/usr/bin/env bash
# Verifies a running browser-desktop container end to end:
# healthy, CDP up, Chrome sandbox, landscape/portrait pixels, transparent cursors,
# Unicode input, remote pinyin from scancode keys, wrong-password rejection, session reuse, and the browser surviving
# viewer disconnects. VERIFY_RESTART=1 (disposable instances only) also restarts the
# container and requires three synthetic tabs to be restored.
# Usage: verify.sh <container> <rdp-host> <rdp-port> <cdp-port> <password-file>
# Env: VERIFY_EVIDENCE (required), DOCKER (default "docker"), APT_MIRROR,
#      VERIFY_SANDBOX (default 1), VERIFY_RESTART (default 0), VERIFY_SHORTCUTS (default 0),
#      VERIFY_XORG_TEST_LOGS (default 0; export the disposable density fixture's tmpfs logs)
set -euo pipefail
container=$1 rdp_host=$2 rdp_port=$3 cdp_port=$4 password_file=$5
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
umask 077
evidence="${VERIFY_EVIDENCE:?set VERIFY_EVIDENCE to a private directory outside the repository}"
mkdir -p "$evidence"
evidence="$(readlink -f "$evidence")"
read -ra docker <<< "${DOCKER:-docker}"
fail() { echo "FAIL: $*" >&2; exit 1; }
in_box() { "${docker[@]}" exec "$container" "$@"; }
cleanup() {
    result=$?
    trap - EXIT
    if (( result != 0 )); then
        bash "$HERE/diagnose.sh" "$container" "$evidence/failure" \
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
    if [[ -f "$evidence/pinyin-target.json" ]]; then
        if ! node "$HERE/unicode-target.mjs" close "$cdp_port" "$evidence/pinyin-target.json"; then
            echo "FAIL: could not close the synthetic pinyin tab" >&2
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

health="$("${docker[@]}" inspect -f '{{.State.Health.Status}}' "$container")"
[[ "$health" == healthy ]] || fail "container health is $health"
curl -fsS "http://127.0.0.1:${cdp_port}/json/version" >/dev/null || fail "CDP not reachable on ${cdp_port}"
if [[ "${VERIFY_SANDBOX:-1}" == 1 ]]; then
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
browser_before="$(in_box pgrep -o -x chrome)"
xorg_before="$(in_box pgrep -o -x Xorg)"
session_before="$(in_box pgrep -o -x xrdp-sesexec)"
[[ "$(in_box pgrep -c -x Xorg)" == 1 ]] || fail "expected exactly one Xorg before login"

sesman_lines="$(in_box sh -c 'wc -l < /var/log/xrdp-sesman.log')"
xrdp_lines="$(in_box sh -c 'wc -l < /var/log/xrdp.log')"
base_args=()
[[ -z ${DEBIAN_IMAGE:-} ]] || base_args+=(--build-arg "DEBIAN_IMAGE=$DEBIAN_IMAGE")
"${docker[@]}" build --progress plain --network host \
    "${base_args[@]}" \
    --build-arg APT_MIRROR="${APT_MIRROR:-http://deb.debian.org}" \
    --build-arg HTTP_PROXY="${HTTP_PROXY:-}" --build-arg HTTPS_PROXY="${HTTPS_PROXY:-}" \
    --build-arg http_proxy="${http_proxy:-}" --build-arg https_proxy="${https_proxy:-}" \
    --build-arg NO_PROXY="${NO_PROXY:-}" --build-arg no_proxy="${no_proxy:-}" \
    -t browser-desktop-rdp-client:visual "$HERE/rdp-client" > "$evidence/client-build.log" 2>&1 || {
        tail -n 25 "$evidence/client-build.log" >&2
        fail 'RDP verification client image build failed'
    }
node "$HERE/visual-target.mjs" open "$cdp_port" "$evidence/target.json"
for phase in 1 2; do
    "${docker[@]}" run --rm --init --network host \
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
    "${docker[@]}" run --rm --init --network host \
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
"${docker[@]}" run --rm --init --network host \
    -e RDP_USER="$desktop_user" \
    -e RDP_CHECK_SHORTCUTS="${VERIFY_SHORTCUTS:-0}" \
    -v "$(readlink -f "$password_file"):/pw:ro" -v "$evidence:/evidence" \
    browser-desktop-rdp-client:visual \
    timeout 80 xvfb-run -a -s '-screen 0 1280x800x24' python3 /unicode-input.py "$rdp_host" "$rdp_port" \
    > "$evidence/unicode-client-result.log" 2>&1 || fail "RDP Unicode client failed; see $evidence"
if [[ "${VERIFY_SHORTCUTS:-0}" == 1 ]]; then
    "${docker[@]}" run --rm --init --network host \
        -e RDP_USER="$desktop_user" -e RDP_NATIVE_SHORTCUTS_ONLY=1 \
        -v "$(readlink -f "$password_file"):/pw:ro" -v "$evidence:/evidence" \
        browser-desktop-rdp-client:visual \
        timeout 80 xvfb-run -a -s '-screen 0 1280x800x24' python3 /unicode-input.py "$rdp_host" "$rdp_port" \
        > "$evidence/native-shortcuts-result.log" 2>&1 || fail "RDP native shortcuts client failed; see $evidence"
fi
node "$HERE/unicode-target.mjs" check "$cdp_port" "$evidence/unicode-target.json" \
    > "$evidence/unicode-value.json" || fail "RDP Unicode text did not reach the input"
# A scancode-only viewer (Jump Desktop with a physical keyboard) types Chinese through
# the remote pinyin engine. This connection follows the Unicode one, so it also proves the
# Unicode engine handed the session back to pinyin on disconnect.
node "$HERE/unicode-target.mjs" open "$cdp_port" "$evidence/pinyin-target.json"
"${docker[@]}" run --rm --init --network host \
    -e RDP_USER="$desktop_user" \
    -v "$(readlink -f "$password_file"):/pw:ro" -v "$evidence:/evidence" \
    browser-desktop-rdp-client:visual \
    timeout 80 xvfb-run -a -s '-screen 0 1280x800x24' python3 /pinyin-input.py "$rdp_host" "$rdp_port" \
    > "$evidence/pinyin-client-result.log" 2>&1 || fail "RDP pinyin client failed; see $evidence"
node "$HERE/unicode-target.mjs" check-composition "$cdp_port" "$evidence/pinyin-target.json" 你好 \
    > "$evidence/pinyin-value.json" || fail "remote pinyin did not turn scancode keys into Chinese"
node "$HERE/unicode-target.mjs" close "$cdp_port" "$evidence/pinyin-target.json" || fail 'could not close the synthetic pinyin tab'
rm "$evidence/pinyin-target.json"
auth_lines="$(in_box sh -c 'wc -l < /var/log/xrdp-sesman.log')"
"${docker[@]}" run --rm --init --network host -v "$evidence:/evidence" browser-desktop-rdp-client:visual \
    timeout 15 xvfb-run -a python3 /reject-rdp.py "$rdp_host" "$rdp_port" "$desktop_user" \
    > "$evidence/rdp-wrong-auth-run.log" 2>&1 || true
in_box tail -n "+$((auth_lines + 1))" /var/log/xrdp-sesman.log > "$evidence/rdp-wrong-auth-server.log"
grep -qF "AUTHFAIL: user=$desktop_user " "$evidence/rdp-wrong-auth-server.log" || fail 'wrong RDP password was not rejected'
if grep -q 'reconnected session:' "$evidence/rdp-wrong-auth-server.log"; then fail 'wrong RDP password reached the session'; fi

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
[[ "$(in_box pgrep -o -x chrome)" == "$browser_before" ]] || fail "browser restarted during login/disconnect"
curl -fsS "http://127.0.0.1:${cdp_port}/json/version" >/dev/null || fail "CDP lost after disconnect"
# Close the synthetic tabs now: a restart restores them under new target IDs.
node "$HERE/visual-target.mjs" close "$cdp_port" "$evidence/target.json" || fail 'could not close the synthetic test tab'
rm "$evidence/target.json"
node "$HERE/unicode-target.mjs" close "$cdp_port" "$evidence/unicode-target.json" || fail 'could not close the synthetic Unicode tab'
rm "$evidence/unicode-target.json"
if [[ "${VERIFY_RESTART:-0}" == 1 ]]; then
    node "$HERE/restart-tabs.mjs" prepare "$cdp_port" "$evidence/restart-tabs.json"
    if [[ "${VERIFY_XORG_TEST_LOGS:-0}" == 1 ]]; then
        [[ "${VERIFY_DISPOSABLE:-0}" == 1 ]] || fail 'Xorg test log export requires a disposable fixture'
        mkdir -p "$evidence/xorg-before-restart"
        "${docker[@]}" exec "$container" tar -C /run/xrdp/test-logs -cf - . |
            tar --no-same-owner -xf - -C "$evidence/xorg-before-restart" \
            || fail 'could not preserve Xorg logs before restart'
    fi
    "${docker[@]}" restart -t 30 "$container" >/dev/null
    for _ in $(seq 1 60); do
        [[ "$("${docker[@]}" inspect -f '{{.State.Health.Status}}' "$container")" == healthy ]] && break
        sleep 3
    done
    node "$HERE/restart-tabs.mjs" check "$cdp_port" "$evidence/restart-tabs.json" \
        || fail 'synthetic tabs were not restored after a container restart'
fi
echo "OK: sandbox, landscape/portrait pixels, rotation clicks, transparent cursors, Chinese (Unicode and remote pinyin) and wrong-password rejection verified; session reused and browser survived disconnect; evidence $evidence"
