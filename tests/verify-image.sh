#!/usr/bin/env bash
# Run the fixed-viewport legacy suite in its own disposable desktop. Density
# transitions have separate real-input/pixel gates in display-scale-image.sh.
set -euo pipefail
umask 077
HERE=$(cd -- "$(dirname -- "$0")" && pwd)
REPO=$(dirname "$HERE")
image=${1:?image reference}
evidence=${2:?private evidence directory}
read -r -a docker <<< "${DOCKER:-docker}"
name="bd-verify-$$"
rdp_port=${RDP_TEST_PORT:-13393}
cdp_port=${CDP_TEST_PORT:-19393}
mkdir -p "$evidence"
evidence=$(cd "$evidence" && pwd)
[[ ! -e "$evidence/container-id" ]] || { echo 'Use a fresh evidence directory' >&2; exit 2; }
cleanup() {
    result=$?
    trap - EXIT
    "${docker[@]}" logs "$name" > "$evidence/server.log" 2>&1 || true
    if [[ $("${docker[@]}" inspect -f '{{.State.Running}}' "$name" 2>/dev/null) == true ]]; then
        mkdir -p "$evidence/xorg-logs"
        if ! "${docker[@]}" exec "$name" tar -C /run/xrdp/test-logs -cf - . |
                tar --no-same-owner -xf - -C "$evidence/xorg-logs"; then
            echo 'FAIL: could not preserve disposable Xorg logs' >&2
            result=1
        fi
    fi
    "${docker[@]}" stop -t 30 "$name" >/dev/null 2>&1 || true
    "${docker[@]}" rm -f "$name" >/dev/null 2>&1 || true
    rm -f "$evidence/password"
    exit "$result"
}
trap cleanup EXIT
"${docker[@]}" run -d --name "$name" --label browser-desktop.test=verify \
    --shm-size 2g --tmpfs /run/xrdp:rw,nosuid,nodev,size=16m,mode=0755 \
    --security-opt "seccomp=$REPO/seccomp/chrome.json" \
    -p "127.0.0.1:$rdp_port:3389" -p "127.0.0.1:$cdp_port:9222" \
    -v "$HERE/xorg-test-entrypoint.sh:/test-entrypoint.sh:ro" \
    --entrypoint /bin/bash -e CDP_BIND_ADDRESS=0.0.0.0 "$image" /test-entrypoint.sh \
    > "$evidence/container-id"
for _ in $(seq 1 60); do
    status=$("${docker[@]}" inspect -f '{{.State.Health.Status}}' "$name")
    [[ $status == healthy ]] && break
    sleep 2
done
[[ $status == healthy ]] || { echo 'Synthetic desktop did not become healthy' >&2; exit 1; }
"${docker[@]}" cp "$name:/data/rdp/password" "$evidence/password"
VERIFY_EVIDENCE="$evidence" VERIFY_RESTART=1 VERIFY_DISPOSABLE=1 VERIFY_SHORTCUTS=1 VERIFY_XORG_TEST_LOGS=1 \
    bash "$HERE/verify.sh" "$name" 127.0.0.1 "$rdp_port" "$cdp_port" "$evidence/password"
