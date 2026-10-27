ARG DEBIAN_IMAGE=public.ecr.aws/docker/library/debian:trixie-slim@sha256:a29215f6a35e51e22adffa17f89e9d2ef06214e64a2bad10d765c46aea49f11f

FROM ${DEBIAN_IMAGE} AS xrdp-build
ARG APT_MIRROR=http://deb.debian.org
COPY image/apt/preferences /etc/apt/preferences.d/browser-desktop
COPY image/apt/write-sources.sh /usr/local/sbin/write-sources.sh
RUN sh /usr/local/sbin/write-sources.sh "$APT_MIRROR" \
    && printf '\nPackage: libx264-dev\nPin: release n=forky\nPin-Priority: 991\n' >> /etc/apt/preferences.d/browser-desktop \
    && apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    autoconf automake libtool pkg-config gcc g++ make nasm curl ca-certificates xz-utils patch \
    libssl-dev libpam0g-dev libjpeg-dev libfuse3-dev libopus-dev libmp3lame-dev \
    libx264-dev libopenh264-dev libx11-dev libxfixes-dev libxrandr-dev libibus-1.0-dev libglib2.0-dev libxtst-dev
WORKDIR /build
# Retain the pinned release; backport the upstream Unicode input path instead of
# upgrading to an unreviewed development branch. Checksums/provenance are in patches/.
RUN curl -fL --retry 3 https://github.com/neutrinolabs/xrdp/releases/download/v0.10.6.1/xrdp-0.10.6.1.tar.gz -o xrdp.tar.gz \
    && echo '2f7beb5a3b2529c8d72dc0df9b8cdca31ab0e0c14d1e3421210f5e6ec0ab3b75  xrdp.tar.gz' | sha256sum -c - \
    && tar -xzf xrdp.tar.gz
COPY image/patches/ /patches/
RUN cd xrdp-0.10.6.1 \
    && patch -p1 < /patches/xrdp-0.10.6.1-ibus-unicode.patch \
    && patch -p1 < /patches/legacy-pointer.patch \
    && patch -p1 < /patches/queued-resize.patch \
    && patch -p1 < /patches/ordered-unicode.patch \
    && patch -p1 < /patches/lazy-unicode-engine.patch \
    && patch -p1 < /patches/large-bitmap.patch \
    && patch -p1 < /patches/display-scale.patch \
    && autoreconf -fi \
    && ./configure --prefix=/usr --sysconfdir=/etc --localstatedir=/var \
    --libdir=/usr/lib/x86_64-linux-gnu --libexecdir=/usr/lib/x86_64-linux-gnu \
    --with-socketdir=/run/xrdp/sockdir --enable-ipv6 --enable-jpeg --enable-fuse \
    --enable-rfxcodec --enable-mp3lame --enable-opus --enable-x264 --enable-openh264 \
    --enable-painter --enable-pam --enable-pam-config=debian --enable-vsock --enable-ibus \
    CFLAGS='-O2 -fstack-protector-strong -fstack-clash-protection -Wformat -Werror=format-security -fcf-protection' \
    CPPFLAGS='-D_FORTIFY_SOURCE=2' LDFLAGS='-Wl,-z,relro -Wl,-z,now -Wl,--as-needed' \
    && make -j4 && make DESTDIR=/out install

FROM ${DEBIAN_IMAGE}
ARG APT_MIRROR=http://deb.debian.org
# forky provides only the RDP stack (xrdp 0.10 with GFX/H.264); everything else is trixie.
ARG XRDP_VERSION=0.10.6.1-3
ARG XORGXRDP_VERSION=1:0.10.5-2
# Pin the official package and verify its bytes; provenance is the signed
# Google Linux repository's Packages index.
ARG CHROME_VERSION=155.0.8059.84-1
ARG CHROME_SHA256=8fbd2ae69cdf7ee98b7513c3396a7b5e06f974f8625fdd590df3091dd0c3e9de
COPY image/apt/preferences /etc/apt/preferences.d/browser-desktop
COPY image/apt/write-sources.sh /usr/local/sbin/write-sources.sh
# ssl-cert generates a snakeoil key at install time; every image would share it.
# Delete it in the same layer; the entrypoint installs the per-container TLS identity.
RUN sh /usr/local/sbin/write-sources.sh "$APT_MIRROR" \
    && printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d && chmod 755 /usr/sbin/policy-rc.d \
    && apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    xrdp=${XRDP_VERSION} xorgxrdp=${XORGXRDP_VERSION} xserver-xorg-core xserver-xorg-legacy \
    openbox supervisor socat curl ca-certificates libnss3-tools openssl xsettingsd \
    x11-utils x11-xserver-utils xauth fonts-noto-cjk fonts-noto-color-emoji \
    python3 python3-websocket procps ibus ibus-gtk3 ibus-libpinyin dbus-x11 \
    && curl -fL --retry 3 \
        "https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_${CHROME_VERSION}_amd64.deb" \
        -o /var/cache/google-chrome.deb \
    && echo "${CHROME_SHA256}  /var/cache/google-chrome.deb" | sha256sum -c - \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends /var/cache/google-chrome.deb \
    && rm -f /var/cache/google-chrome.deb /etc/apt/sources.list.d/google-chrome.list \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home --shell /bin/bash browser \
    && sed -i 's/^AllowRootLogin=.*/AllowRootLogin=false/;s/^MaxSessions=.*/MaxSessions=1/;s/^Policy=.*/Policy=UB/;s/^KillDisconnected=.*/KillDisconnected=false/;s/^IdleTimeLimit=.*/IdleTimeLimit=0/;s/^param=Xorg$/param=\/usr\/lib\/xorg\/Xorg/' /etc/xrdp/sesman.ini \
    && sed -i 's/^security_layer=.*/security_layer=tls/;s/^tcp_nodelay=.*/tcp_nodelay=true/;s/^new_cursors=.*/new_cursors=false/' /etc/xrdp/xrdp.ini \
    && rm -f /etc/ssl/private/ssl-cert-snakeoil.key /etc/ssl/certs/ssl-cert-snakeoil.pem /etc/xrdp/key.pem /etc/xrdp/cert.pem

# Keep Debian's configuration, PAM rules and package-created users/directories.
COPY --from=xrdp-build /out/usr/sbin/ /usr/sbin/
COPY --from=xrdp-build /out/usr/bin/ /usr/bin/
COPY --from=xrdp-build /out/usr/lib/x86_64-linux-gnu/ /usr/lib/x86_64-linux-gnu/
# XTest primes Chrome's XIM context before its first Unicode commit.
# Fail the build if the required runtime library is absent.
RUN dpkg-query -W -f='${Status}\n' libxtst6 | grep -qx 'install ok installed' \
    && ldconfig

ENV DESKTOP_USER=browser \
    BROWSER_PROFILE_DIR=/data/profile \
    BROWSER_DOWNLOADS_DIR=/data/downloads \
    RDP_STATE_DIR=/data/rdp \
    RDP_BIND_ADDRESS=0.0.0.0 \
    RDP_PORT=3389 \
    CDP_BIND_ADDRESS=127.0.0.1 \
    CDP_PORT=9222 \
    BROWSER_PROXY_SERVER= \
    BROWSER_PROXY_BYPASS= \
    TZ=Asia/Shanghai \
    LANGUAGE=zh_CN \
    LANG=C.UTF-8 LC_CTYPE=C.UTF-8 GTK_IM_MODULE=xim XMODIFIERS=@im=ibus \
    CURSOR_STYLE=arrow \
    SESSION_GEOMETRY=1366x768
EXPOSE 3389
COPY image/entrypoint.sh /entrypoint.sh
COPY image/startwm.sh /etc/xrdp/startwm.sh
COPY image/ibus-session.sh /usr/local/bin/ibus-session.sh
COPY image/display-scale.py /usr/local/bin/display-scale.py
COPY image/configure-openbox.py image/configure-cursors.py /usr/local/libexec/
COPY image/supervisord.conf /etc/supervisor/browser.conf
COPY image/browser-desktop.gschema.override /usr/share/glib-2.0/schemas/90_browser-desktop.gschema.override
COPY image/gtk-settings.ini /etc/gtk-3.0/settings.ini
COPY seccomp/chrome.json /usr/share/browser-desktop/chrome-seccomp.json
COPY LICENSE NOTICE /usr/share/doc/browser-desktop/
COPY image/patches/ /usr/share/doc/browser-desktop/patches/
RUN chmod 755 /entrypoint.sh /etc/xrdp/startwm.sh /usr/local/bin/ibus-session.sh /usr/local/bin/display-scale.py \
    && python3 -I /usr/local/libexec/configure-openbox.py \
    && python3 -I /usr/local/libexec/configure-cursors.py \
    && /usr/lib/x86_64-linux-gnu/glib-2.0/glib-compile-schemas /usr/share/glib-2.0/schemas \
    && dpkg-query -W -f='${Package} ${Version}\n' > /usr/share/doc/browser-desktop/packages.txt
ARG IMAGE_VERSION=dev
ARG IMAGE_REVISION=unknown
ARG IMAGE_CREATED=unknown
LABEL org.opencontainers.image.title="browser-desktop" \
      org.opencontainers.image.description="Persistent Google Chrome desktop over RDP" \
      org.opencontainers.image.source="https://github.com/puchunwei/browser-desktop" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      org.opencontainers.image.revision="${IMAGE_REVISION}" \
      org.opencontainers.image.created="${IMAGE_CREATED}"
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD /entrypoint.sh health
ENTRYPOINT ["/entrypoint.sh"]
