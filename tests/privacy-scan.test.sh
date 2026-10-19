#!/usr/bin/env bash
# Exercises privacy-scan.sh tree mode with throwaway repositories.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
work="$(mktemp -d "${TMPDIR:-/tmp}/privacy-test.XXXXXX")"
trap 'rm -rf "$work"' EXIT
git_t() { git -C "$1" -c user.name=test -c user.email=test@example.invalid "${@:2}"; }
new_repo() { git init -q "$work/$1"; git_t "$work/$1" commit -q --allow-empty -m init; }
expect() {
    local want=$1 got; shift
    if "$@" > "$work/out" 2>&1; then got=pass; else got=fail; fi
    [[ "$got" == "$want" ]] || { cat "$work/out" >&2; echo "FAIL: expected $want: $*" >&2; exit 1; }
}
scan() { bash "$HERE/privacy-scan.sh" tree "$1"; }

new_repo clean
echo hello > "$work/clean/a.txt"; git_t "$work/clean" add a.txt; git_t "$work/clean" commit -q -m add
expect pass scan "$work/clean"

new_repo token
# Build the token at runtime so this test file never contains one.
printf 'token=%s\n' "gh""p_$(printf 'A%.0s' {1..24})" > "$work/token/a.txt"
expect fail scan "$work/token"

new_repo history
echo 'marker-7f3a' > "$work/history/b.txt"; git_t "$work/history" add b.txt; git_t "$work/history" commit -q -m add
git_t "$work/history" rm -q b.txt; git_t "$work/history" commit -q -m remove
printf '# comment\nmarker-7f3a\n' > "$work/patterns"
expect pass scan "$work/history"
PRIVATE_PATTERNS_FILE="$work/patterns" expect fail scan "$work/history"

new_repo meta
git_t "$work/meta" commit -q --allow-empty -m 'mention marker-7f3a'
PRIVATE_PATTERNS_FILE="$work/patterns" expect fail scan "$work/meta"

expect fail bash "$HERE/privacy-scan.sh" bogus "$work/clean"
echo 'OK: privacy-scan tree mode'
