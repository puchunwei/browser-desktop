#!/usr/bin/env bash
# Start the image with good and bad configurations and check its documented behavior.
# Usage: startup-checks.sh <image>
# Env: DOCKER (default "docker"); REQUIRE_SANDBOX=1 (default) demands Chrome's namespace
# sandbox when the repository seccomp profile is applied; 0 accepts a logged fallback.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(dirname "$HERE")"
image=${1:?usage: startup-checks.sh <image>}
read -ra docker <<< "${DOCKER:-docker}"
prefix="bd-check-$$"
cleanup() {
    "${docker[@]}" ps -aq --filter "name=^$prefix-" | xargs -r "${docker[@]}" rm -f >/dev/null
    "${docker[@]}" volume ls -q --filter "name=^$prefix-" | xargs -r "${docker[@]}" volume rm >/dev/null
}
trap cleanup EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }
base=(--tmpfs /run/xrdp:rw,nosuid,nodev,size=16m,mode=0755 --shm-size 2g)
in_c() { "${docker[@]}" exec "$prefix-$1" "${@:2}"; }

expect_refusal() {
    local name=$1 message=$2 output; shift 2
    if output="$(timeout 120 "${docker[@]}" run --rm --name "$prefix-$name" "$@" "$image" 2>&1)"; then
        fail "$name: container exited successfully although it should refuse"
    fi
    grep -qF -- "$message" <<<"$output" || { echo "$output" >&2; fail "$name: missing message: $message"; }
    echo "OK: $name refused"
}
wait_healthy() {
    local name="$prefix-$1" status
    for _ in $(seq 1 60); do
        status="$("${docker[@]}" inspect -f '{{.State.Status}} {{.State.Health.Status}}' "$name")"
        case "$status" in
            'running healthy') return 0 ;;
            running*) sleep 3 ;;
            *) "${docker[@]}" logs "$name" >&2 || true; fail "$1 stopped: $status" ;;
        esac
    done
    "${docker[@]}" logs "$name" >&2 || true
    fail "$1 did not become healthy"
}

expect_refusal no-tmpfs '/run/xrdp must be a tmpfs' --shm-size 2g
expect_refusal small-shm '/dev/shm must be at least 1 GiB' --tmpfs /run/xrdp:rw,nosuid,nodev,size=16m,mode=0755 --shm-size 64m
expect_refusal root-user 'DESKTOP_USER must match' "${base[@]}" -e DESKTOP_USER=root
expect_refusal system-user 'is a reserved system account' "${base[@]}" -e DESKTOP_USER=xrdp
expect_refusal missing-secret 'missing RDP password file /run/secrets/rdp' "${base[@]}" -e RDP_PASSWORD_FILE=/run/secrets/rdp
expect_refusal bad-tz 'unknown TZ' "${base[@]}" -e TZ=Mars/Base
"${docker[@]}" volume create "$prefix-newer" >/dev/null
"${docker[@]}" run --rm -v "$prefix-newer:/data" --entrypoint sh "$image" \
    -c 'mkdir -p /data/profile && echo 999.0.0.0 > "/data/profile/Last Version"'
expect_refusal newer-profile 'refusing to downgrade' "${base[@]}" -v "$prefix-newer:/data"
"${docker[@]}" volume create "$prefix-private" >/dev/null
"${docker[@]}" run --rm -v "$prefix-private:/data" --entrypoint sh "$image" -c 'chown 4242:4242 /data && chmod 0700 /data'
expect_refusal private-data 'must be writable by the desktop user' "${base[@]}" -v "$prefix-private:/data"

# First start on an empty volume with a custom account and Docker's default seccomp.
"${docker[@]}" volume create "$prefix-alice" >/dev/null
"${docker[@]}" run -d --name "$prefix-alice" "${base[@]}" --stop-timeout 30 \
    -e DESKTOP_USER=alice -v "$prefix-alice:/data" "$image" >/dev/null
wait_healthy alice
[[ "$(in_c alice id -nu 1000)" == alice ]] || fail 'uid 1000 was not renamed to alice'
[[ "$(in_c alice stat -c '%a %U' /data/rdp/password)" == '600 root' ]] || fail 'password file is not private'
password="$(in_c alice cat /data/rdp/password)"
(( ${#password} >= 20 )) || fail 'generated password is too short'
logs="$("${docker[@]}" logs "$prefix-alice" 2>&1)"
if grep -qF -- "$password" <<<"$logs"; then fail 'password appeared in logs'; fi
grep -q 'RDP TLS certificate SHA256 ' <<<"$logs" || fail 'certificate fingerprint not logged'
grep -q 'Chrome sandbox unavailable' <<<"$logs" || fail 'missing sandbox fallback warning'
in_c alice pgrep -u alice -x chrome >/dev/null || fail 'Chrome is not running as alice'
in_c alice pgrep -a -u alice -x chrome | grep -q -- '--no-sandbox' || fail 'fallback did not add --no-sandbox'
if in_c alice sh -c 'command -v x11vnc || command -v vncpasswd || command -v chromium'; then
    fail 'VNC tools or Debian Chromium are still installed'
fi
for file in LICENSE NOTICE packages.txt patches/queued-resize.patch; do
    in_c alice test -s "/usr/share/doc/browser-desktop/$file" || fail "missing /usr/share/doc/browser-desktop/$file"
done
in_c alice test -s /usr/share/browser-desktop/chrome-seccomp.json || fail 'seccomp profile not shipped'
[[ "$(in_c alice cat /etc/timezone)" == Asia/Shanghai ]] || fail 'timezone not applied'
in_c alice curl -fsS http://127.0.0.1:9222/json/version >/dev/null || fail 'CDP not reachable inside the container'
"${docker[@]}" restart -t 30 "$prefix-alice" >/dev/null
wait_healthy alice
[[ "$(in_c alice cat /data/rdp/password)" == "$password" ]] || fail 'password changed across restart'
[[ "$(in_c alice id -nu 1000)" == alice ]] || fail 'account changed across restart'
echo 'OK: first start, restart, generated secrets and image contents'

# Repository seccomp profile plus a wildcard CDP listener.
"${docker[@]}" run -d --name "$prefix-sandbox" "${base[@]}" --security-opt "seccomp=$REPO/seccomp/chrome.json" \
    -e CDP_BIND_ADDRESS=0.0.0.0 "$image" >/dev/null
wait_healthy sandbox
logs="$("${docker[@]}" logs "$prefix-sandbox" 2>&1)"
grep -q 'without authentication' <<<"$logs" || fail 'non-loopback CDP did not warn'
if in_c sandbox pgrep -a -u browser -x chrome | grep -q -- '--no-sandbox'; then
    grep -q 'Chrome sandbox unavailable' <<<"$logs" || fail 'Chrome runs without sandbox and without a warning'
    [[ "${REQUIRE_SANDBOX:-1}" != 1 ]] || fail 'Chrome sandbox unavailable with the repository seccomp profile'
    echo 'NOTE: this host blocks user namespaces; the logged fallback was verified instead'
else
    if grep -q 'Chrome sandbox unavailable' <<<"$logs"; then fail 'sandbox warning although the sandbox is active'; fi
    echo 'OK: Chrome sandbox active with the repository seccomp profile'
fi
echo 'OK: startup checks passed'
