#!/bin/sh
# Runs as the desktop user; the browser connects through XIM.
# Usage: /usr/local/bin/ibus-session.sh
set -eu

export LANG=C.UTF-8 LC_CTYPE=C.UTF-8
export GTK_IM_MODULE=ibus QT_IM_MODULE=ibus XMODIFIERS=@im=ibus

# sesman starts chansrv separately, so it may not inherit this D-Bus address.
# libibus discovers this user's address file by UID + DISPLAY instead.
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
    exec /usr/bin/dbus-run-session -- "$0" "$@"
fi

/usr/bin/ibus-daemon --daemonize --xim --panel=disable --config=disable
# Ensure an ordinary engine exists before the first RDP client connects.
# The xrdp Unicode engine records this engine and restores it on disconnect.
attempt=0
until /usr/bin/ibus engine xkb:us::eng >/dev/null 2>&1 \
    && /usr/bin/xprop -root XIM_SERVERS 2>/dev/null | grep -q '@server=ibus'; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 50 ]; then
        echo "IBus did not become ready for the desktop session" >&2
        exit 1
    fi
    sleep 0.1
done

# The input method daemon belongs to this bus/session and is not coupled to
# any viewer. Openbox publishes the screen after its own startup, so Chrome
# starts only when both the window manager and input method are ready.
exec /usr/bin/openbox --startup '/entrypoint.sh publish-session'
