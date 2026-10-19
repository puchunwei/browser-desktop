"""Send UTF-8 through FreeRDP's real RDP Unicode keyboard events.

Run only against a disposable browser-desktop fixture. /pw is its synthetic
credential, /evidence is a private evidence directory, and the matching
unicode-target.mjs must have opened the synthetic input page first.
FreeRDP 3.15 xf_client.c:xf_inject_keypress converts the FIFO's UTF-8 to UTF-16
and calls freerdp_input_send_unicode_keyboard_event for press and release.
This deliberately uses neither clipboard redirection nor CDP text injection.
"""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from PIL import Image
from Xlib import X, XK, display
from Xlib.ext import xtest

host, port = sys.argv[1:3]
text = sys.argv[3] if len(sys.argv) > 3 else "中A1文B2输入C3测试D4"
native_only = os.environ.get('RDP_NATIVE_SHORTCUTS_ONLY') == '1'
out = Path("/evidence")
fifo = out / "rdp-unicode.fifo"
fifo.unlink(missing_ok=True)
screen = display.Display()
root = screen.screen().root
args = [f"/v:{host}:{port}", "/u:" + os.environ.get('RDP_USER', 'browser'),
        "/p:" + Path("/pw").read_text().strip(), "/cert:ignore",
        "/size:1280x720", "/gfx", "-clipboard", "/log-level:INFO",
        # FreeRDP's UnicodeInput setting also gates protocol Unicode sends.
        # Native shortcuts therefore use a separate connection without a FIFO.
        "/kbd:unicode:off" if native_only else f"/kbd:unicode:on,pipe:{fifo}"]
with (out / ("native-shortcuts-client.log" if native_only else "unicode-client.log")).open("w") as log:
    client = subprocess.Popen(["xfreerdp3", "/args-from:stdin"],
                              stdin=subprocess.PIPE, stdout=log,
                              stderr=subprocess.STDOUT, text=True,
                              start_new_session=True)
    client.stdin.write("\n".join(args) + "\n")
    client.stdin.close()
    try:
        deadline = time.monotonic() + 45
        green = (27, 181, 91)
        while time.monotonic() < deadline:
            if client.poll() is not None:
                raise RuntimeError(f"RDP client exited with {client.returncode}")
            geometry = root.get_geometry()
            raw = root.get_image(0, 0, geometry.width, geometry.height,
                                 X.ZPixmap, 0xffffffff)
            frame = Image.frombytes("RGB", (geometry.width, geometry.height),
                                    raw.data, "raw", "BGRX")
            points = [(x, y) for y in range(0, frame.height, 8)
                      for x in range(0, frame.width, 8)
                      if all(abs(a - b) < 15 for a, b in
                             zip(frame.getpixel((x, y)), green))]
            if len(points) > 500 and (native_only or fifo.exists()):
                break
            time.sleep(0.25)
        else:
            frame.save(out / "unicode-failed.png")
            raise RuntimeError("synthetic Unicode input page was not visible over RDP")
        # Focus the large green input with a real RDP mouse event.
        x = sum(p[0] for p in points) // len(points)
        y = sum(p[1] for p in points) // len(points)
        xtest.fake_input(screen, X.MotionNotify, x=x, y=y)
        xtest.fake_input(screen, X.ButtonPress, 1)
        xtest.fake_input(screen, X.ButtonRelease, 1)
        screen.sync()
        time.sleep(0.5)
        # The fixture's short text fits in one <63-byte read, preserving UTF-8
        # code point boundaries in FreeRDP's FIFO implementation.
        encoded = text.encode("utf-8")
        if len(encoded) > 60:
            raise ValueError("Unicode fixture must be at most 60 UTF-8 bytes")
        if native_only:
            control = screen.keysym_to_keycode(XK.string_to_keysym('Control_L'))
            for letter in ('a', 'c', 'v'):
                key = screen.keysym_to_keycode(XK.string_to_keysym(letter))
                for kind, code in ((X.KeyPress, control), (X.KeyPress, key),
                                   (X.KeyRelease, key), (X.KeyRelease, control)):
                    xtest.fake_input(screen, kind, code)
                screen.sync()
                time.sleep(0.3)
        else:
            with fifo.open("wb", buffering=0) as pipe:
                pipe.write(encoded)
            time.sleep(2)
        if not native_only and os.environ.get('RDP_CHECK_SHORTCUTS') == '1':
            # A native modifier combined with a Unicode letter must select all.
            control = screen.keysym_to_keycode(XK.string_to_keysym('Control_L'))
            xtest.fake_input(screen, X.KeyPress, control)
            screen.sync()
            time.sleep(0.2)
            with fifo.open('wb', buffering=0) as pipe:
                pipe.write(b'a')
            time.sleep(0.3)
            xtest.fake_input(screen, X.KeyRelease, control)
            screen.sync()
            time.sleep(0.2)
            with fifo.open('wb', buffering=0) as pipe:
                pipe.write(encoded)
            time.sleep(2)
        print("OK: sent " + ("native shortcuts" if native_only else "RDP Unicode events") + "; verify DOM separately",
              flush=True)
    finally:
        if client.poll() is None:
            os.killpg(client.pid, signal.SIGTERM)
        try:
            client.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(client.pid, signal.SIGKILL)
            client.wait()
        screen.close()
        fifo.unlink(missing_ok=True)
