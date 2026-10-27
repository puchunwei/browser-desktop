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
curl -fsSL https://raw.githubusercontent.com/puchunwei/browser-desktop/main/install.sh | bash
```

Downloads `compose.yaml` and `seccomp/chrome.json`, generates a random password, starts the
container, and prints the user name, password and port. Override with
`DESKTOP_USER=alice RDP_PASSWORD='...' bash -c "$(curl -fsSL .../install.sh)"`.
The script only fetches and runs those two public files; read [`install.sh`](install.sh) first if you want.

To inspect or edit the configuration first, clone the repo instead; everything is in the single
root [`compose.yaml`](compose.yaml):

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

## Retina and desktop density

Resolution controls transmitted pixels; desktop density controls the logical size of the
whole Chrome UI. Auto follows valid negotiated RDP desktop density and falls back to 100%
when metadata is missing. It does not guess a device from window dimensions. Scale changes
keep the running browser, tabs, drafts and scroll position; page zoom is independent.

Press **Ctrl+Alt+S** above Chrome to choose Auto, 100% Phone compatibility, 150% Larger text,
200% Mac Retina / 2x phone, or 300% Phone Retina. Examples: 6016×3384 at 200% represents a
3008×1692 logical desktop; 1170×2532 at 300% represents about 390×844.
These phone sizes are synthetic examples, not detected phone models. Check the complete
actual canvas, toolbar and both edges on your device. Use 100% for a 640px portrait
compatibility canvas; 150% needs enough logical width. Client fit-to-window, magnification
and pinch zoom may resample the picture again. Preferences use a stable client hint; without one, overrides last one connection.
Auto clears the current client's override. A hint is a preference key, not an identity.

On Jump mobile, use the keyboard/Keypad to send Ctrl+Alt+S, or long press / two-finger tap
an exposed desktop background and choose Display scale. Right-clicking a webpage opens its
page menu. Three-finger tap toggles the keyboard; three-finger double tap switches iPhone
keyboard/Keypad. See the [official gesture guide](https://support.jumpdesktop.com/hc/en-us/articles/216423503-Getting-Started-Jump-Desktop-Controls-and-Gesture-Reference)
and check the active input mode. Enable the RDP connection's Retina/high-resolution and
dynamic-resolution options as named in your installed Jump version.

Before accepting a real Jump setup, check Mac window/full-screen transitions and accurate
clicks; retain a Chinese/English draft and scroll position while reconnecting on the phone;
check 100% portrait / 150% landscape compatibility and native 300% phone canvases, visible toolbar and both edges, rotation, Chinese input and menu access; then return to Mac and confirm its scale.
Compare text at matched logical size. FreeRDP automation is not real Jump acceptance.
On a 4K Mac monitor using “looks like 3008×1692”, the 6016×3384 render is still resampled
to physical 4K; this final step can soften text and server density cannot remove it.

CI and release gate image delivery on controller units and disposable negotiated RDP/Chrome
integration. Run `bash tests/display-scale-image.sh <image> <private-evidence-dir>` with a
fresh evidence directory. It uses synthetic data, trusted RDP clicks and layout/process
checks. The fixture keeps Xorg logs in the existing `/run/xrdp` tmpfs to isolate overlay
writeback stalls, with checked log exports before restart and cleanup. Shipping log paths
and pixel, input and timeout gates remain unchanged.
With `DENSITY_VERIFY_LEGACY=1`, `tests/verify-image.sh` runs the existing fixed-viewport
suite in a separate disposable desktop, so its color-derived pointer targets do not
inherit the matrix's final 300% transition. The matrix still verifies transition pixels and input.
Fixed reconnects check compressed legacy pixels; the disposable live-grow fixture
uses server-uncompressed bitmaps because the pinned FreeRDP decoder retains its initial
planar bounds after resizing. Existing RFX/AVC rotation tests also run. This fixture setting
does not change the shipped codec policy; verify compressed rotation in actual Jump.
Source/decoded comparisons cover only the tested codec path at matched geometry,
not Jump rendering, subjective sharpness or network performance.
