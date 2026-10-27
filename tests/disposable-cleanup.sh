#!/usr/bin/env bash
# Sourced by disposable runners; uses their Docker command array.
cleanup_disposable_server() {
    local result=$1 name=$2 evidence=$3 recorded actual
    recorded=$(cat "$evidence/container-id" 2>/dev/null) || recorded=''
    actual=$("${docker[@]}" inspect -f '{{.Id}}' "$name" 2>/dev/null) || actual=''
    if [[ -n $actual ]]; then
        # Never stop a same-name container that this runner did not create.
        if [[ ! $recorded =~ ^[0-9a-f]{64}$ || $recorded != "$actual" ]]; then
            echo 'FAIL: disposable container identity mismatch' >&2
            rm -f "$evidence/password"
            return 1
        fi
        "${docker[@]}" logs "$name" > "$evidence/server.log" 2>&1 || true
        if [[ $("${docker[@]}" inspect -f '{{.State.Running}}' "$name") == true ]]; then
            mkdir -p "$evidence/xorg-logs"
            # docker cp cannot read this runtime tmpfs on every Docker backend.
            if ! "${docker[@]}" exec "$name" tar -C /run/xrdp/test-logs -cf - . |
                    tar --no-same-owner -xf - -C "$evidence/xorg-logs"; then
                echo 'FAIL: could not preserve disposable Xorg logs' >&2
                result=1
            fi
        fi
        "${docker[@]}" stop -t 30 "$name" >/dev/null 2>&1 || true
        "${docker[@]}" rm -f "$name" >/dev/null 2>&1 || true
    fi
    rm -f "$evidence/password"
    return "$result"
}
