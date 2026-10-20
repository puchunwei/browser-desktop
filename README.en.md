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

Everything is configured in the single root [`compose.yaml`](compose.yaml); no `.env` or other files are needed:

```bash
git clone https://github.com/puchunwei/browser-desktop.git && cd browser-desktop
vi compose.yaml        # set DESKTOP_USER and RDP_PASSWORD (at least 20 characters, no ":")
docker compose up -d
docker compose logs browser-desktop | grep 'RDP TLS certificate SHA256'   # compare on first connect
```

Connect an RDP client to `server:3389` as `DESKTOP_USER` with `RDP_PASSWORD`. With `RDP_PASSWORD` empty,
a random password is generated on first start; read it with `docker exec browser-desktop cat /data/rdp/password`.
`RDP_PASSWORD_FILE` reads it from a file (e.g. a Docker secret) instead; set only one of the two.
Without cloning, download `compose.yaml` and `seccomp/chrome.json`, keeping that relative path.

Keep `shm_size`, the `/run/xrdp` tmpfs and the 30-second stop grace period; the container refuses
to start without the first two, and a shorter stop can lose cookies. The seccomp option enables
Chrome's own sandbox; without it Chrome runs with `--no-sandbox` and the log warns.

Chinese input: phone keyboards send RDP Unicode text directly. Physical keyboards (Jump Desktop,
Windows Remote Desktop and other scancode clients) use the built-in remote pinyin engine: it
starts in English, and Shift toggles Chinese.

Configuration, CDP, backup and troubleshooting are documented in the Chinese [README](README.md);
variable names and log messages are identical. Security notes: [SECURITY.md](SECURITY.md).
