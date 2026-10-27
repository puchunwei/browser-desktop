#!/usr/bin/env bash
# Exercise evidence retention with real, task-owned containers; no RDP service.
set -euo pipefail
umask 077
HERE=$(cd -- "$(dirname -- "$0")" && pwd)
source "$HERE/disposable-cleanup.sh"
read -r -a docker <<< "${DOCKER:-docker}"
image=${1:?image reference}
evidence=${2:?fresh private evidence directory}
mkdir "$evidence"
owned=()
trap 'for id in "${owned[@]}"; do "${docker[@]}" rm -f "$id" >/dev/null 2>&1 || true; done' EXIT
for mode in success export-failure identity-mismatch prior-failure; do
    name="bd-cleanup-$$-$mode"
    directory="$evidence/$mode"
    mkdir "$directory"
    id=$("${docker[@]}" run -d --name "$name" --label browser-desktop.test=cleanup \
        --network none --tmpfs /run/xrdp:rw,nosuid,nodev,size=1m \
        --entrypoint /bin/bash "$image" -c \
        'mkdir -p /run/xrdp/test-logs; echo synthetic-xorg-log > /run/xrdp/test-logs/xorg.log; exec sleep 120')
    owned+=("$id")
    printf '%s\n' "$id" > "$directory/container-id"
    printf 'synthetic-password\n' > "$directory/password"
    for _ in {1..20}; do
        "${docker[@]}" exec "$id" test -f /run/xrdp/test-logs/xorg.log && break
        sleep .1
    done
    "${docker[@]}" exec "$id" test -f /run/xrdp/test-logs/xorg.log
    initial=0 expected=0
    case "$mode" in
        export-failure)
            "${docker[@]}" exec "$id" rm -r /run/xrdp/test-logs
            expected=1 ;;
        identity-mismatch)
            printf 'not-the-created-container\n' > "$directory/container-id"
            expected=1 ;;
        prior-failure) initial=7 expected=7 ;;
    esac
    result=0
    cleanup_disposable_server "$initial" "$name" "$directory" > "$directory/cleanup.log" 2>&1 || result=$?
    [[ $result == "$expected" && ! -e "$directory/password" ]]
    if [[ $mode == identity-mismatch ]]; then
        [[ $("${docker[@]}" inspect -f '{{.State.Running}}' "$id") == true ]]
        printf '%s\n' "$id" > "$directory/container-id"
        cleanup_disposable_server 0 "$name" "$directory"
    fi
    ! "${docker[@]}" inspect "$id" >/dev/null 2>&1
    if [[ $mode == export-failure ]]; then
        rg -q 'FAIL: could not preserve disposable Xorg logs' "$directory/cleanup.log"
    else
        [[ $(cat "$directory/xorg-logs/xorg.log") == synthetic-xorg-log ]]
    fi
    echo "PASS: $mode status=$result, password removed, owned container removed"
done
