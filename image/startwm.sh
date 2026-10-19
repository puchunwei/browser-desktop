#!/bin/sh
# The xrdp session only hosts the window manager. Chrome runs under supervisord as the
# desktop user, outside the session, so viewer disconnects never touch it.
exec /usr/local/bin/ibus-session.sh
