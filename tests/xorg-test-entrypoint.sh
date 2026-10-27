#!/usr/bin/env bash
# Disposable density fixture only. Keep Xorg's synchronous log writes off the
# container overlay filesystem; export these logs before restart and cleanup.
set -euo pipefail
install -d -o browser -g browser -m 0700 /run/xrdp/test-logs
sed -i 's|^param=\.xorgxrdp\.%s\.log$|param=/run/xrdp/test-logs/xorg.%s.log|' /etc/xrdp/sesman.ini
grep -Fxq 'param=/run/xrdp/test-logs/xorg.%s.log' /etc/xrdp/sesman.ini
exec /entrypoint.sh "$@"
