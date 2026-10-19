#!/usr/bin/env bash
# Read-only snapshot. Run before recreating a failed container so its logs survive.
# Deliberately exclude environment, process arguments and browser/profile contents.
set -euo pipefail
umask 077
container="${1:?usage: diagnose.sh <container> <private-evidence-dir>}"
evidence="${2:?usage: diagnose.sh <container> <private-evidence-dir>}"
mkdir -p "$evidence"
chmod 0700 "$evidence"
read -ra docker <<< "${DOCKER:-docker}"
in_box() { "${docker[@]}" exec "$container" "$@"; }
"${docker[@]}" inspect -f '{{.Id}} {{.Config.Image}} {{.State.Status}} restarts={{.RestartCount}} oom={{.State.OOMKilled}}' \
    "$container" > "$evidence/container.txt"
capture() {
    local name=$1
    shift
    if ! in_box "$@" > "$evidence/$name" 2>&1; then
        printf '\nDiagnostic unavailable: %s\n' "$name" >> "$evidence/$name"
    fi
}
capture processes.txt ps -eo pid,ppid,comm
capture session.txt cat /run/browser-desktop/session
capture xrdp.log cat /var/log/xrdp.log
capture sesman.log cat /var/log/xrdp-sesman.log
user="$(in_box printenv DESKTOP_USER)"
display="$(in_box sed -n 's/^DISPLAY=://p' /run/browser-desktop/session)"
display="${display%%.*}"
if [[ "$user" =~ ^[a-z_][a-z0-9_-]{0,30}$ && "$display" =~ ^[0-9]+$ ]]; then
    capture xorg.log cat "/home/$user/.xorgxrdp.$display.log"
fi
printf 'Diagnostic evidence: %s\n' "$evidence"
