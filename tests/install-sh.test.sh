#!/usr/bin/env bash
# Checks install.sh's input validation without touching the network or Docker.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
script="$HERE/../install.sh"
bash_bin="$(command -v bash)"
bash -n "$script"

# Each case sets its own PATH (defaulting to the real one) so the Docker-detection
# cases below can run with no "docker" reachable at all, unlike the real host's.
# bash itself is invoked by absolute path: a restricted PATH must not hide bash too.
expect_fail() {
    local message=$1 output; shift
    if output="$(env -i PATH="${TEST_PATH:-$PATH}" "$@" "$bash_bin" "$script" 2>&1)"; then
        echo "FAIL: expected failure: $*" >&2; exit 1
    fi
    grep -qF -- "$message" <<<"$output" || { echo "$output" >&2; echo "FAIL: missing message: $message" >&2; exit 1; }
}

expect_fail 'RDP_PASSWORD must be at least 20 characters' BROWSER_DESKTOP_DIR=/nonexistent/unused RDP_PASSWORD=short
expect_fail 'DESKTOP_USER must match' BROWSER_DESKTOP_DIR=/nonexistent/unused DESKTOP_USER=root RDP_PASSWORD=ok-password-0123456789

# With RDP_PASSWORD set, nothing before the Docker checks needs an external program,
# so an empty PATH genuinely has no "docker" reachable (this host otherwise does).
empty_path="$(mktemp -d "${TMPDIR:-/tmp}/install-sh-empty-path.XXXXXX")"
trap 'rm -rf "$empty_path"' EXIT
TEST_PATH="$empty_path" expect_fail 'install Docker and the Compose plugin first' \
    BROWSER_DESKTOP_DIR=/nonexistent/unused RDP_PASSWORD=ok-password-0123456789

# A "docker" that exists but rejects every subcommand stands in for a missing Compose plugin.
fake_bin="$(mktemp -d "${TMPDIR:-/tmp}/install-sh-fake-docker.XXXXXX")"
trap 'rm -rf "$empty_path" "$fake_bin"' EXIT
printf '#!/usr/bin/env bash\nexit 1\n' > "$fake_bin/docker"
chmod +x "$fake_bin/docker"
TEST_PATH="$fake_bin:/usr/bin:/bin" expect_fail 'install the Docker Compose plugin first' \
    BROWSER_DESKTOP_DIR=/nonexistent/unused RDP_PASSWORD=ok-password-0123456789

echo 'OK: install.sh rejects a short password, the root account and a missing Docker/Compose before touching the network'
