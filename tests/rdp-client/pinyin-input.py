"""Type Chinese through the remote pinyin engine with scancode-only RDP keys.

Run only against a disposable or owner-approved browser-desktop session. /pw is
its credential, /evidence a private evidence directory, and unicode-target.mjs
must have opened the synthetic input page first. Unicode keyboard input is off,
like Jump Desktop with a physical keyboard: every key reaches the server as a
scancode, so only the remote IBus pinyin engine can produce Chinese text.
Shift switches pinyin to Chinese, "nihao" plus Space commits the first
candidate, and a final Shift restores English mode for the session.
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
out = Path("/evidence")
screen = display.Display()
root = screen.screen().root
args = [f"/v:{host}:{port}", "/u:" + os.environ.get('RDP_USER', 'browser'),
        "/p:" + Path("/pw").read_text().strip(), "/cert:ignore",
        "/size:1280x720", "/gfx", "-clipboard", "/log-level:INFO", "/kbd:unicode:off"]


def tap(name, hold=0.08):
    code = screen.keysym_to_keycode(XK.string_to_keysym(name))
    xtest.fake_input(screen, X.KeyPress, code)
    screen.sync()
    time.sleep(hold)
    xtest.fake_input(screen, X.KeyRelease, code)
    screen.sync()
    time.sleep(0.15)


with (out / "pinyin-client.log").open("w") as log:
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
            if len(points) > 500:
                break
            time.sleep(0.25)
        else:
            frame.save(out / "pinyin-failed.png")
            raise RuntimeError("synthetic input page was not visible over RDP")
        # Focus the large green input with a real RDP mouse event.
        x = sum(p[0] for p in points) // len(points)
        y = sum(p[1] for p in points) // len(points)
        xtest.fake_input(screen, X.MotionNotify, x=x, y=y)
        xtest.fake_input(screen, X.ButtonPress, 1)
        xtest.fake_input(screen, X.ButtonRelease, 1)
        screen.sync()
        time.sleep(1)
        tap('Shift_L')
        for letter in 'nihao':
            tap(letter)
        time.sleep(0.8)
        geometry = root.get_geometry()
        raw = root.get_image(0, 0, geometry.width, geometry.height, X.ZPixmap, 0xffffffff)
        Image.frombytes("RGB", (geometry.width, geometry.height), raw.data, "raw", "BGRX").save(out / "pinyin-candidates.png")
        tap('space')
        time.sleep(0.8)
        tap('Shift_L')
        time.sleep(0.5)
        print("OK: sent scancode pinyin keys; verify DOM separately", flush=True)
    finally:
        if client.poll() is None:
            os.killpg(client.pid, signal.SIGTERM)
        try:
            client.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(client.pid, signal.SIGKILL)
            client.wait()
        screen.close()
