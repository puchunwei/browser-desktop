# browser-desktop

A persistent Google Chrome desktop used remotely over RDP. The browser and its tabs keep
running after you disconnect, and you return to the same screen. The desktop follows the
client's resolution, including phone rotation and phone-keyboard Chinese input. Programs on
the same host can drive the same browser through the Chrome DevTools Protocol (CDP).

- Image: `ghcr.io/puchunwei/browser-desktop`, linux/amd64 only (verified on Linux AMD64 only).
- One instance serves one trusted person. Run separate instances and volumes for several people.
- The image contains unmodified Google Chrome. **By using it you accept the
  [Google Chrome Terms of Service](https://www.google.com/chrome/terms/).**
- Other third-party components and licenses: `/usr/share/doc/browser-desktop/NOTICE` in the image.

## Quick start

```bash
mkdir browser-desktop && cd browser-desktop
curl -fsSLO https://raw.githubusercontent.com/puchunwei/browser-desktop/main/examples/compose.yml
docker run --rm --entrypoint cat ghcr.io/puchunwei/browser-desktop:latest \
  /usr/share/browser-desktop/chrome-seccomp.json > chrome-seccomp.json
docker compose up -d
docker compose logs browser-desktop | grep 'RDP TLS certificate SHA256'   # compare on first connect
docker exec browser-desktop cat /data/rdp/password                         # RDP password
```

Connect an RDP client to `server:3389` as `DESKTOP_USER` (default `browser`).

Keep `--tmpfs /run/xrdp`, `--shm-size 2g` and a 30-second stop timeout; the container refuses
to start without the first two, and a shorter stop can lose cookies. The seccomp option enables
Chrome's own sandbox; without it Chrome runs with `--no-sandbox` and the log warns.

Configuration, CDP, backup and troubleshooting are documented in the Chinese [README](README.md);
variable names and log messages are identical. Security notes: [SECURITY.md](SECURITY.md).
