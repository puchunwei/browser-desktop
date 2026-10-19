# Throwaway FreeRDP client for verify.sh; never deployed.
FROM public.ecr.aws/docker/library/debian:trixie-slim
COPY sources.list /etc/apt/sources.list
RUN rm -f /etc/apt/sources.list.d/debian.sources && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends freerdp3-x11 tigervnc-viewer tigervnc-tools xvfb xauth ca-certificates python3 python3-xlib python3-pil \
    && rm -rf /var/lib/apt/lists/*
COPY visual-client.py /visual-client.py
COPY cursor-probe.py /cursor_probe.py
COPY unicode-input.py /unicode-input.py
COPY rotation-client.py /rotation-client.py
