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

# The default panel draws the pinyin candidate window. ibus-libpinyin exits unless the
# IBus config component (ibus-dconf) is running; its defaults come from the image's gschema
# override (pinyin starts in English mode, Shift toggles Chinese).
/usr/bin/ibus-daemon --daemonize --xim
# Select the pinyin engine before the first RDP client connects. Scancode viewers
# (for example Jump Desktop) type through it; the xrdp Unicode engine takes over
# only when a viewer sends Unicode characters, and restores this engine on disconnect.
# "ibus engine libpinyin" reports failure even when the switch succeeds, so check the
# resulting engine instead of the command's exit status.
attempt=0
until { /usr/bin/ibus engine libpinyin >/dev/null 2>&1; [ "$(/usr/bin/ibus engine 2>/dev/null)" = libpinyin ]; } \
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
