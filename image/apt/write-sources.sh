#!/bin/sh
# Write the Debian sources used by this image. Usage: write-sources.sh <mirror-base-url>
# Examples: http://deb.debian.org (default), http://mirrors.aliyun.com
set -eu
mirror=${1%/}
case "$mirror" in
    http://*|https://*) ;;
    *) echo 'APT_MIRROR must be an http(s) base URL' >&2; exit 1 ;;
esac
rm -f /etc/apt/sources.list.d/debian.sources
cat > /etc/apt/sources.list <<EOF
deb $mirror/debian trixie main
deb $mirror/debian trixie-updates main
deb $mirror/debian-security trixie-security main
deb $mirror/debian forky main
EOF
