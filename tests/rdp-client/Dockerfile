# Throwaway FreeRDP client for verify.sh; never deployed.
ARG DEBIAN_IMAGE=public.ecr.aws/docker/library/debian:trixie-slim@sha256:a29215f6a35e51e22adffa17f89e9d2ef06214e64a2bad10d765c46aea49f11f
FROM ${DEBIAN_IMAGE}
ARG APT_MIRROR=http://deb.debian.org
RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf 'deb %s/debian trixie main\ndeb %s/debian-security trixie-security main\n' "$APT_MIRROR" "$APT_MIRROR" > /etc/apt/sources.list \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends freerdp3-x11 xvfb xauth ca-certificates python3 python3-xlib python3-pil python3-websocket \
    && rm -rf /var/lib/apt/lists/*
COPY visual-client.py /visual-client.py
COPY cursor-probe.py /cursor_probe.py
COPY unicode-input.py /unicode-input.py
COPY rotation-client.py /rotation-client.py
COPY reject-rdp.py /reject-rdp.py
COPY pinyin-input.py /pinyin-input.py
COPY large-display.py /large-display.py
COPY display-scale.py /display-scale.py
