#!/usr/bin/env bash
# One-command install: downloads the release compose file and seccomp profile,
# fills in a user and password, and starts the container.
#   curl -fsSL https://raw.githubusercontent.com/puchunwei/browser-desktop/main/install.sh | bash
# Override DESKTOP_USER / RDP_PASSWORD as environment variables to skip the generated values;
# set BROWSER_DESKTOP_DIR to install somewhere other than ./browser-desktop.
set -euo pipefail
dir="${BROWSER_DESKTOP_DIR:-browser-desktop}"
user="${DESKTOP_USER:-browser}"
[[ "$user" =~ ^[a-z_][a-z0-9_-]{0,30}$ && "$user" != root ]] || { echo "DESKTOP_USER must match ^[a-z_][a-z0-9_-]{0,30}\$ and must not be root" >&2; exit 1; }
password="${RDP_PASSWORD:-}"
if [[ -z "$password" ]]; then
    password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))' 2>/dev/null \
        || openssl rand -base64 18 2>/dev/null \
        || { echo "need python3 or openssl to generate a password; set RDP_PASSWORD instead" >&2; exit 1; })"
fi
(( ${#password} >= 20 )) && [[ "$password" != *:* ]] || { echo "RDP_PASSWORD must be at least 20 characters without \":\"" >&2; exit 1; }
command -v docker >/dev/null || { echo "install Docker and the Compose plugin first: https://docs.docker.com/engine/install/" >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "install the Docker Compose plugin first: https://docs.docker.com/compose/install/" >&2; exit 1; }

raw="https://raw.githubusercontent.com/puchunwei/browser-desktop/main"
mkdir -p "$dir/seccomp"
curl -fsSL "$raw/compose.yaml" -o "$dir/compose.yaml"
curl -fsSL "$raw/seccomp/chrome.json" -o "$dir/seccomp/chrome.json"
python3 - "$dir/compose.yaml" "$user" "$password" <<'PY'
import sys
path, user, password = sys.argv[1:4]
text = open(path, encoding='utf-8').read()
text = text.replace('DESKTOP_USER: "browser"', f'DESKTOP_USER: "{user}"', 1)
text = text.replace('RDP_PASSWORD: ""', f'RDP_PASSWORD: "{password}"', 1)
open(path, 'w', encoding='utf-8').write(text)
PY
( cd "$dir" && docker compose up -d )

cat <<EOF

已部署到 ./$dir
RDP 用户名： $user
RDP 密码：   $password
RDP 端口：   3389（见 ./$dir/compose.yaml 的 ports）

用 RDP 客户端（Windows App / Microsoft Remote Desktop / Jump Desktop / FreeRDP）连接本机的 3389 端口。
密码等信息不会再次打印；忘记了用 docker exec browser-desktop cat /data/rdp/password 读取。
EOF
