#!/bin/bash
set -euo pipefail

session_file=/run/browser-desktop/session
browser_executable=/usr/bin/google-chrome-stable
# publish-session runs inside the xrdp session, which does not inherit the container
# environment; every value used there must have a default or come from the session.
export DESKTOP_USER="${DESKTOP_USER:-browser}"
# Remember whether the deployer chose a password file before applying the default.
password_file_set="${RDP_PASSWORD_FILE:+1}"
export RDP_PASSWORD_FILE="${RDP_PASSWORD_FILE:-${RDP_STATE_DIR:-/data/rdp}/password}"

fail() { echo "browser-desktop: $*" >&2; exit 1; }
warn() { echo "browser-desktop: WARNING: $*" >&2; }
# Wildcard listeners are probed through loopback.
probe_host() { if [[ "$1" == 0.0.0.0 ]]; then echo 127.0.0.1; else echo "$1"; fi; }

# Openbox invokes this only after both IBus and the window manager are ready.
# Publishing earlier lets Chrome miss its startup maximize request.
if [[ "${1:-}" == "publish-session" ]]; then
    umask 022
    xhost +SI:localuser:"$(id -un)" >/dev/null
    printf 'DISPLAY=%s\nXAUTHORITY=%s\n' "$DISPLAY" "${XAUTHORITY:-$HOME/.Xauthority}" > "$session_file.tmp"
    mv -f "$session_file.tmp" "$session_file"
    exit 0
fi

# Succeeds when the session's screen accepts X clients; exports its DISPLAY/XAUTHORITY.
load_display() {
    [[ -f "$session_file" ]] || return 1
    # shellcheck disable=SC1090
    set -a; . "$session_file"; set +a
    xdpyinfo >/dev/null 2>&1
}

# The browser waits for the xrdp session, which may be recreated at any time.
if [[ "${1:-}" == "wait-display" ]]; then
    shift
    until load_display; do sleep 0.5; done
    exec "$@"
fi

# The density controller owns xsettingsd as the desktop user, never as root.
if [[ "${1:-}" == "display-scale" ]]; then
    exec /usr/sbin/runuser -u "$DESKTOP_USER" -- /usr/local/bin/display-scale.py serve
fi

# One persistent session for the configured desktop user.
if [[ "${1:-}" == "session" ]]; then
    while true; do
        if ! load_display; then
            rm -f "$session_file"
            xrdp-sesrun -t Xorg -g "$SESSION_GEOMETRY" -F 3 "$DESKTOP_USER" 3<"$RDP_PASSWORD_FILE" \
                || echo "xrdp-sesrun failed, retrying" >&2
            for ((i=0; i<40; i++)); do load_display && break; sleep 0.5; done
        fi
        sleep 5
    done
fi

if [[ "${1:-}" == "health" ]]; then
    curl -fsS "http://$(probe_host "$CDP_BIND_ADDRESS"):${CDP_PORT}/json/version" >/dev/null
    load_display
    exec 3<>"/dev/tcp/$(probe_host "$RDP_BIND_ADDRESS")/${RDP_PORT}"
    exit 0
fi

# SIGTERM alone does not reliably flush Chrome's cookie database. Ask CDP
# to close the browser normally before Supervisor stops the session.
if [[ "${1:-}" == "browser" ]]; then
    shift
    # Chrome must see the initial XSettings owner before creating its UI.
    until /usr/sbin/runuser -u "$DESKTOP_USER" -- /usr/local/bin/display-scale.py status >/dev/null; do
        sleep 0.5
    done
    proxy_args=()
    if [[ -n "${BROWSER_PROXY_SERVER:-}" ]]; then
        proxy_args+=("--proxy-server=${BROWSER_PROXY_SERVER}")
        [[ -n "${BROWSER_PROXY_BYPASS:-}" ]] && proxy_args+=("--proxy-bypass-list=${BROWSER_PROXY_BYPASS}")
    fi
    /usr/sbin/runuser -u "$DESKTOP_USER" -- "$browser_executable" "$@" "${proxy_args[@]}" &
    browser_pid=$!
    shutdown_browser() {
        trap '' TERM INT
        timeout 10s python3 -I - <<'PY' || kill -TERM "$browser_pid" 2>/dev/null || true
import json, urllib.request, websocket
v = json.load(urllib.request.urlopen('http://127.0.0.1:9223/json/version', timeout=3))
# Chrome rejects CDP websockets that carry an Origin header.
ws = websocket.create_connection(v['webSocketDebuggerUrl'], timeout=5, suppress_origin=True)
ws.send(json.dumps({'id': 1, 'method': 'Browser.close'}))
try:
    while ws.recv():
        pass
except Exception:
    pass
PY
        wait "$browser_pid" || true
        exit 0
    }
    trap shutdown_browser TERM INT
    wait "$browser_pid"
    exit $?
fi

# --- container start: one-time setup as root, then supervisord ---

[[ "$DESKTOP_USER" =~ ^[a-z_][a-z0-9_-]{0,30}$ && "$DESKTOP_USER" != root ]] \
    || fail 'DESKTOP_USER must match ^[a-z_][a-z0-9_-]{0,30}$ and must not be root'
existing_uid="$(id -u "$DESKTOP_USER" 2>/dev/null || true)"
existing_gid="$(getent group "$DESKTOP_USER" | cut -d: -f3 || true)"
if [[ ( -n "$existing_uid" && "$existing_uid" != 1000 ) || ( -n "$existing_gid" && "$existing_gid" != 1000 ) ]]; then
    fail "DESKTOP_USER $DESKTOP_USER is a reserved system account"
fi
case "${CURSOR_STYLE:-arrow}" in
    arrow) export XCURSOR_PATH=/usr/local/share/browser-cursors ;;
    native) export XCURSOR_PATH=/nonexistent-cursor-themes ;;
    *) fail 'CURSOR_STYLE must be arrow or native' ;;
esac
[[ "$TZ" =~ ^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+)*$ && -f "/usr/share/zoneinfo/$TZ" ]] || fail "unknown TZ $TZ"
[[ "$(stat -f -c %T /run/xrdp 2>/dev/null || true)" == tmpfs ]] \
    || fail '/run/xrdp must be a tmpfs: add --tmpfs /run/xrdp:rw,nosuid,nodev,size=16m,mode=0755'
shm_kib="$(df -k --output=size /dev/shm | tail -n 1 | tr -d ' ')"
(( shm_kib >= 1048576 )) || fail '/dev/shm must be at least 1 GiB: add --shm-size 2g'
for dir in "$BROWSER_PROFILE_DIR" "$BROWSER_DOWNLOADS_DIR" "$RDP_STATE_DIR"; do
    { mkdir -p "$dir" && touch "$dir/.write-test" && rm -f "$dir/.write-test"; } 2>/dev/null \
        || fail "$dir must be a writable directory"
done

# The image ships uid 1000 as "browser"; rename it once per container.
current_user="$(id -nu 1000)"
if [[ "$current_user" != "$DESKTOP_USER" ]]; then
    groupmod -n "$DESKTOP_USER" "$(id -ng 1000)"
    usermod -l "$DESKTOP_USER" -d "/home/$DESKTOP_USER" -m "$current_user"
fi
ln -sf "/usr/share/zoneinfo/$TZ" /etc/localtime
echo "$TZ" > /etc/timezone

# RDP_PASSWORD and RDP_PASSWORD_FILE follow the usual VAR / VAR_FILE convention: set at most one.
# A configured RDP_PASSWORD is stored privately on every start so a changed value takes effect;
# without either, a password is generated once at the default location.
check_password() {
    python3 -I - "$1" <<'PY'
import pathlib, sys
password = pathlib.Path(sys.argv[1]).read_text().strip()
if len(password) < 20 or any(c in password for c in ':\r\n'):
    raise SystemExit('RDP password must be at least 20 characters without ":" or newlines')
PY
}
if [[ -n "${RDP_PASSWORD:-}" ]]; then
    [[ -z "$password_file_set" ]] || fail 'set either RDP_PASSWORD or RDP_PASSWORD_FILE, not both'
    ( umask 077; printf '%s\n' "$RDP_PASSWORD" > "$RDP_PASSWORD_FILE.new" )
    check_password "$RDP_PASSWORD_FILE.new" || { rm -f "$RDP_PASSWORD_FILE.new"; exit 1; }
    mv -f "$RDP_PASSWORD_FILE.new" "$RDP_PASSWORD_FILE"
elif [[ ! -e "$RDP_PASSWORD_FILE" && "$RDP_PASSWORD_FILE" == "$RDP_STATE_DIR/password" ]]; then
    ( umask 077; python3 -I -c 'import secrets; print(secrets.token_urlsafe(24))' > "$RDP_PASSWORD_FILE.new" )
    mv -f "$RDP_PASSWORD_FILE.new" "$RDP_PASSWORD_FILE"
    echo "browser-desktop: generated an RDP password; read it with: docker exec <container> cat $RDP_PASSWORD_FILE"
fi
[[ -s "$RDP_PASSWORD_FILE" ]] || fail "missing RDP password file $RDP_PASSWORD_FILE"
# Supervised programs, including Chrome, must not inherit the password.
unset RDP_PASSWORD
chmod 0700 "$RDP_STATE_DIR"
python3 -I - "$RDP_PASSWORD_FILE" <<'PY' | chpasswd
import os, pathlib, sys
password = pathlib.Path(sys.argv[1]).read_text().strip()
if len(password) < 20 or any(c in password for c in ':\r\n'):
    raise SystemExit('RDP password must be at least 20 characters without ":" or newlines')
print(os.environ['DESKTOP_USER'] + ':' + password)
PY

# Never open a profile written by a newer browser: a downgrade can corrupt it.
mkdir -p "$BROWSER_PROFILE_DIR/Default"
image_version="$("$browser_executable" --version | grep -oE '[0-9]+(\.[0-9]+){3}')"
if [[ -f "$BROWSER_PROFILE_DIR/Last Version" ]]; then
    profile_version="$(tr -d '[:space:]' < "$BROWSER_PROFILE_DIR/Last Version")"
    if [[ "$(printf '%s\n%s\n' "$profile_version" "$image_version" | sort -V | tail -1)" != "$image_version" ]]; then
        fail "profile was written by browser $profile_version, image has $image_version; refusing to downgrade"
    fi
fi

# The TLS identity persists with the state dir so RDP clients trust it only once.
tls="$RDP_STATE_DIR/tls"
mkdir -p "$tls"
if [[ ! -s "$tls/key.pem" || ! -s "$tls/cert.pem" ]]; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj '/CN=browser-desktop' \
        -addext 'subjectAltName=DNS:browser-desktop,DNS:localhost,IP:127.0.0.1' \
        -addext 'extendedKeyUsage=serverAuth' \
        -keyout "$tls/key.pem" -out "$tls/cert.pem" 2>/dev/null
fi
install -m 0640 -o root -g xrdp "$tls/key.pem" /etc/xrdp/key.pem
install -m 0644 -o root -g xrdp "$tls/cert.pem" /etc/xrdp/cert.pem
echo "browser-desktop: RDP TLS certificate SHA256 $(openssl x509 -noout -fingerprint -sha256 -in "$tls/cert.pem" | cut -d= -f2)"

# Only [Globals] port is the listener; [Xorg] keeps port=-1, which means "ask sesman".
# Drive, sound and printer redirection stay off.
sed -i "/^\[Globals\]/,/^\[/ s|^port=.*|port=tcp://${RDP_BIND_ADDRESS}:${RDP_PORT}|" /etc/xrdp/xrdp.ini
sed -i 's/^rdpdr=.*/rdpdr=false/;s/^rdpsnd=.*/rdpsnd=false/' /etc/xrdp/xrdp.ini
case "$CDP_BIND_ADDRESS" in
    127.*) ;;
    *) warn "CDP listens on $CDP_BIND_ADDRESS:$CDP_PORT without authentication; publish it only to a host loopback address" ;;
esac

install -d -o xrdp -g xrdp -m 0755 /run/xrdp
# Only the desktop user and the authenticated xrdp worker can use this IPC.
install -d -o "$DESKTOP_USER" -g xrdp -m 2770 /run/xrdp/display-scale
install -d -o root -g root -m 1777 /tmp/.X11-unix /tmp/.ICE-unix
install -d -o "$DESKTOP_USER" -g "$DESKTOP_USER" -m 0755 /run/browser-desktop
rm -f "$session_file" /run/xrdp/*.pid

if [[ -d /ca-anchors ]]; then
    nssdb="/home/$DESKTOP_USER/.pki/nssdb"
    mkdir -p "$nssdb"
    [[ -f "$nssdb/cert9.db" ]] || certutil -N -d "sql:$nssdb" --empty-password
    for certificate in /ca-anchors/*.crt; do
        [[ -f "$certificate" ]] || continue
        nickname="host-$(basename "$certificate")"
        cp "$certificate" "/usr/local/share/ca-certificates/$nickname"
        certutil -D -d "sql:$nssdb" -n "$nickname" >/dev/null 2>&1 || true
        certutil -A -d "sql:$nssdb" -t "C,," -n "$nickname" -i "$certificate"
    done
    chown -R "$DESKTOP_USER:$DESKTOP_USER" "/home/$DESKTOP_USER/.pki"
    update-ca-certificates
fi

# Chrome's namespace sandbox needs unprivileged user namespaces, which Docker's
# default seccomp profile blocks. Fall back visibly instead of failing to start.
if /usr/sbin/runuser -u "$DESKTOP_USER" -- unshare --user --map-root-user true 2>/dev/null; then
    export BROWSER_SANDBOX_FLAGS=
else
    export BROWSER_SANDBOX_FLAGS=--no-sandbox
    warn 'Chrome sandbox unavailable because user namespaces are blocked; run with --security-opt seccomp=chrome-seccomp.json (see README)'
fi

# Containers have different hostnames on recreation; stale Chrome locks are invalid.
rm -f "$BROWSER_PROFILE_DIR/SingletonLock" "$BROWSER_PROFILE_DIR/SingletonCookie" "$BROWSER_PROFILE_DIR/SingletonSocket"
python3 -I - <<'PYTHON'
import json, os
from pathlib import Path
p = Path(os.environ['BROWSER_PROFILE_DIR']) / 'Default/Preferences'
prefs = json.loads(p.read_text()) if p.exists() else {}
prefs.setdefault('download', {}).update(default_directory=os.environ['BROWSER_DOWNLOADS_DIR'], prompt_for_download=False)
p.write_text(json.dumps(prefs))
PYTHON
chown -R "$DESKTOP_USER:$DESKTOP_USER" "$BROWSER_PROFILE_DIR" "$BROWSER_DOWNLOADS_DIR"
# Chrome runs as the desktop user. If it cannot reach its profile it silently uses a
# default one and ignores --remote-debugging-port, so check the path as that user.
for dir in "$BROWSER_PROFILE_DIR" "$BROWSER_DOWNLOADS_DIR"; do
    /usr/sbin/runuser -u "$DESKTOP_USER" -- test -w "$dir" -a -x "$dir" \
        || fail "$dir must be writable by the desktop user (uid 1000); check the permissions of every parent directory"
done
exec /usr/bin/supervisord -c /etc/supervisor/browser.conf
