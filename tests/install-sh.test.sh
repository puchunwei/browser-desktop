#!/usr/bin/env bash
# Checks install.sh's input validation without touching the network or Docker.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
script="$HERE/../install.sh"
bash -n "$script"

expect_fail() {
    local message=$1 output; shift
    if output="$(env -i PATH="$PATH" "$@" bash "$script" 2>&1)"; then
        echo "FAIL: expected failure: $*" >&2; exit 1
    fi
    grep -qF -- "$message" <<<"$output" || { echo "$output" >&2; echo "FAIL: missing message: $message" >&2; exit 1; }
}

expect_fail 'RDP_PASSWORD must be at least 20 characters' env BROWSER_DESKTOP_DIR=/nonexistent/unused RDP_PASSWORD=short
expect_fail 'DESKTOP_USER must match' env BROWSER_DESKTOP_DIR=/nonexistent/unused DESKTOP_USER=root RDP_PASSWORD=ok-password-0123456789
echo 'OK: install.sh rejects a short password and the root account before touching the network'
