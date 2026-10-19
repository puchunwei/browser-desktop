#!/usr/bin/env bash
# Fail when public material contains private markers. Matched text is never printed.
# Usage: privacy-scan.sh tree <git-dir> | image <image-ref>
# Built-in patterns cover private keys and GitHub tokens only. Owner-specific
# patterns (one extended regex per line, "#" comments) come from PRIVATE_PATTERNS_FILE.
# Image mode uses DOCKER (default "docker") and skips path prefixes listed in
# privacy-allow.txt next to this script.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
mode=${1:-} target=${2:-}
if [[ ( "$mode" != tree && "$mode" != image ) || -z "$target" ]]; then
    echo 'usage: privacy-scan.sh tree <git-dir> | image <image-ref>' >&2
    exit 2
fi
work="$(mktemp -d "${TMPDIR:-/tmp}/privacy-scan.XXXXXX")"
trap 'chmod -R u+rwX "$work" 2>/dev/null || true; rm -rf "$work"' EXIT
patterns="$work/patterns"
printf '%s\n' 'BEGIN [A-Z ]*PRIVATE KEY' 'ghp_[A-Za-z0-9]{20}' 'github_pat_[A-Za-z0-9_]{20}' > "$patterns"
if [[ -n "${PRIVATE_PATTERNS_FILE:-}" ]]; then
    grep -v -E '^[[:space:]]*(#|$)' "$PRIVATE_PATTERNS_FILE" >> "$patterns"
fi
found=0
report() { echo "PRIVACY: $1" >&2; found=1; }

if [[ "$mode" == tree ]]; then
    cd "$target"
    revisions="$(git rev-list --all)"
    if [[ -n "$revisions" ]]; then
        # shellcheck disable=SC2086
        hits="$(git grep -I -l -E -f "$patterns" $revisions -- || true)"
        [[ -z "$hits" ]] || report "committed files: $(tr '\n' ' ' <<<"$hits")"
        if git log --all --format='%an%n%ae%n%cn%n%ce%n%B' | grep -q -E -f "$patterns"; then
            report 'commit metadata or messages'
        fi
    fi
    hits="$(git ls-files -co --exclude-standard -z | xargs -0 -r grep -I -l -E -f "$patterns" -- || true)"
    [[ -z "$hits" ]] || report "working tree: $(tr '\n' ' ' <<<"$hits")"
else
    read -ra docker <<< "${DOCKER:-docker}"
    if "${docker[@]}" history --no-trunc "$target" | grep -q -E -f "$patterns"; then report 'image history'; fi
    if "${docker[@]}" image inspect "$target" | grep -q -E -f "$patterns"; then report 'image config'; fi
    mkdir "$work/image"
    "${docker[@]}" save "$target" | tar -x -C "$work/image"
    allow=()
    while read -r line; do
        [[ -z "$line" || "$line" == \#* ]] || allow+=("${line%%[[:space:]]*}")
    done < "$HERE/privacy-allow.txt"
    while read -r layer; do
        rm -rf "$work/rootfs"; mkdir "$work/rootfs"
        tar -x -f "$work/image/$layer" -C "$work/rootfs" --no-same-owner --no-same-permissions \
            --exclude='dev/*' 2>/dev/null || true
        chmod -R u+rX "$work/rootfs" 2>/dev/null || true
        while IFS= read -r file; do
            relative="${file#"$work/rootfs/"}"
            allowed=0
            for prefix in "${allow[@]}"; do [[ "$relative" == "$prefix"* ]] && allowed=1; done
            (( allowed )) || report "layer ${layer##*/}: $relative"
        done < <(grep -r -I -l -E -f "$patterns" "$work/rootfs" || true)
    done < <(python3 -I -c 'import json, sys; print(*json.load(open(sys.argv[1]))[0]["Layers"], sep="\n")' "$work/image/manifest.json")
fi
(( found == 0 )) || { echo 'privacy scan FAILED' >&2; exit 1; }
echo "privacy scan OK: $mode $target"
