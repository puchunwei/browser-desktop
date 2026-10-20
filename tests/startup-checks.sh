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
    local name=$1 message=$2 output status; shift 2
    # Run detached and poll: timeout cannot stop a long-running "sudo docker" client, because sudo
    # does not relay signals from its own process group to the root-owned docker process.
    "${docker[@]}" run -d --name "$prefix-$name" "$@" "$image" >/dev/null
    status=timeout
    for _ in $(seq 1 60); do
        if [[ "$("${docker[@]}" inspect -f '{{.State.Running}}' "$prefix-$name")" == false ]]; then
            status="$("${docker[@]}" inspect -f '{{.State.ExitCode}}' "$prefix-$name")"
            break
        fi
        sleep 2
    done
    output="$("${docker[@]}" logs "$prefix-$name" 2>&1)"
    "${docker[@]}" rm -f "$prefix-$name" >/dev/null
    [[ "$status" != timeout ]] || fail "$name: still running after 120 s although it should refuse"
    [[ "$status" != 0 ]] || fail "$name: container exited successfully although it should refuse"
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
expect_refusal short-password 'RDP password must be at least 20 characters' "${base[@]}" -e RDP_PASSWORD=too-short
expect_refusal both-passwords 'set either RDP_PASSWORD or RDP_PASSWORD_FILE' "${base[@]}" \
    -e RDP_PASSWORD=configured-password-0123456789 -e RDP_PASSWORD_FILE=/run/secrets/rdp
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
in_c alice test -s /usr/share/ibus/component/libpinyin.xml || fail 'remote pinyin engine not installed'
# No taskbar exists, so nothing may iconify a window that can then never be restored.
in_c alice grep -qx 'gtk-decoration-layout=:maximize,close' /etc/gtk-3.0/settings.ini || fail 'Chrome still offers a minimize button'
if in_c alice grep -Eq 'action name="(Iconify|ToggleShowDesktop)"|client-menu|<titleLayout>[^<]*I' /etc/xdg/openbox/rc.xml; then
    fail 'Openbox can still iconify windows'
fi
[[ "$(in_c alice cat /etc/timezone)" == Asia/Shanghai ]] || fail 'timezone not applied'
in_c alice curl -fsS http://127.0.0.1:9222/json/version >/dev/null || fail 'CDP not reachable inside the container'
"${docker[@]}" restart -t 30 "$prefix-alice" >/dev/null
wait_healthy alice
[[ "$(in_c alice cat /data/rdp/password)" == "$password" ]] || fail 'password changed across restart'
[[ "$(in_c alice id -nu 1000)" == alice ]] || fail 'account changed across restart'
echo 'OK: first start, restart, generated secrets and image contents'

# A configured password replaces the stored one on every start and never reaches logs or children.
configured='configured-password-0123456789'
"${docker[@]}" run -d --name "$prefix-configured" "${base[@]}" --stop-timeout 30 \
    -e DESKTOP_USER=carol -e RDP_PASSWORD="$configured" "$image" >/dev/null
wait_healthy configured
[[ "$(in_c configured cat /data/rdp/password)" == "$configured" ]] || fail 'RDP_PASSWORD was not applied'
[[ "$(in_c configured stat -c '%a %U' /data/rdp/password)" == '600 root' ]] || fail 'configured password file is not private'
logs="$("${docker[@]}" logs "$prefix-configured" 2>&1)"
if grep -qF -- "$configured" <<<"$logs"; then fail 'configured password appeared in logs'; fi
if grep -q 'generated an RDP password' <<<"$logs"; then fail 'a password was generated although RDP_PASSWORD was set'; fi
chrome_pid="$(in_c configured pgrep -o -u carol -x chrome)"
if in_c configured sh -c "tr '\\0' '\\n' < /proc/$chrome_pid/environ" | grep -q '^RDP_PASSWORD='; then
    fail 'RDP_PASSWORD leaked into the Chrome environment'
fi
echo 'OK: configured RDP password applied privately'

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
