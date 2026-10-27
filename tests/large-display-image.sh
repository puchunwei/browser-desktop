#!/usr/bin/env bash
# Start a disposable desktop and test the legacy bitmap path at large sizes.
set -euo pipefail
HERE=$(cd -- "$(dirname -- "$0")" && pwd)
REPO=$(dirname "$HERE")
image=${1:?image reference}
evidence=${2:?private evidence directory}
read -r -a docker <<< "${DOCKER:-docker}"
name="bd-large-$$"
rdp_port=${RDP_TEST_PORT:-13390}
cdp_port=${CDP_TEST_PORT:-19290}
mkdir -p "$evidence"
evidence=$(cd "$evidence" && pwd)
cleanup() {
    "${docker[@]}" stop -t 30 "$name" >/dev/null 2>&1 || true
    "${docker[@]}" rm -f "$name" >/dev/null 2>&1 || true
    rm -f "$evidence/password"
}
trap cleanup EXIT
"${docker[@]}" run -d --name "$name" --label browser-desktop.test=large-display \
    --shm-size 2g --tmpfs /run/xrdp:rw,nosuid,nodev,size=16m,mode=0755 \
    --security-opt "seccomp=$REPO/seccomp/chrome.json" \
    -p "127.0.0.1:$rdp_port:3389" -p "127.0.0.1:$cdp_port:9222" \
    -e CDP_BIND_ADDRESS=0.0.0.0 "$image" > "$evidence/container-id"
for _ in $(seq 1 60); do
    status=$("${docker[@]}" inspect -f '{{.State.Health.Status}}' "$name")
    [[ $status == healthy ]] && break
    sleep 2
done
[[ $status == healthy ]] || { echo 'Synthetic desktop did not become healthy' >&2; exit 1; }
"${docker[@]}" cp "$name:/data/rdp/password" "$evidence/password"
client_image=${RDP_CLIENT_IMAGE:-browser-desktop-rdp-client:visual}
if [[ -z ${RDP_CLIENT_IMAGE:-} ]]; then
    base_args=()
    [[ -z ${DEBIAN_IMAGE:-} ]] || base_args+=(--build-arg "DEBIAN_IMAGE=$DEBIAN_IMAGE")
    "${docker[@]}" build --network host --build-arg "APT_MIRROR=${APT_MIRROR:-http://deb.debian.org}" \
        "${base_args[@]}" \
        --build-arg "HTTP_PROXY=${HTTP_PROXY:-}" --build-arg "HTTPS_PROXY=${HTTPS_PROXY:-}" \
        --build-arg "http_proxy=${http_proxy:-}" --build-arg "https_proxy=${https_proxy:-}" \
        --build-arg "NO_PROXY=${NO_PROXY:-}" --build-arg "no_proxy=${no_proxy:-}" \
        -t "$client_image" "$HERE/rdp-client" > "$evidence/client-build.log" 2>&1 || {
            tail -n 12 "$evidence/client-build.log" >&2
            exit 1
        }
fi
VERIFY_DISPOSABLE=1 RDP_CLIENT_IMAGE="$client_image" bash "$HERE/large-display.sh" \
    "$name" 127.0.0.1 "$rdp_port" "$cdp_port" "$evidence/password" "$evidence/results"
