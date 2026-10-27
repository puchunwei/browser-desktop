"""Check decoded pixels in the legacy 32-bit bitmap path on a large desktop.

Use only a disposable server showing tests/rotation-target.mjs. The test never
connects to a personal desktop or reads its profile.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from PIL import Image
from Xlib import X, display
from Xlib.ext import xtest

host, port = sys.argv[1:3]
width, height = map(int, sys.argv[3].split('x'))
out = Path('/evidence')
screen = display.Display()
root = screen.screen().root
colors = [(235, 52, 67), (40, 190, 90), (35, 95, 220), (235, 185, 35)]
args = [f'/v:{host}:{port}', '/u:browser',
        '/p:' + Path('/pw').read_text().strip(), '/cert:ignore',
        f'/size:{width}x{height}', '/bpp:32', '/network:modem',
        '-rfx', '-nsc', '/cache:bitmap:off',
        '-decorations', '/log-level:INFO']
client = None
try:
    with (out/'freerdp.log').open('w') as log:
        client = subprocess.Popen(['xfreerdp3', '/args-from:stdin'],
            stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
            text=True, start_new_session=True)
        client.stdin.write('\n'.join(args) + '\n')
        client.stdin.close()
        deadline = time.monotonic() + 35
        # Include both sides of the 4096-pixel plane limit, and both ends.
        xs = [32, width//4, width//2-32, width//2+32,
              min(width-32, 4080), min(width-32, 4120), width-32]
        ys = [180, height//2-64, height//2+128, height-32]
        while time.monotonic() < deadline:
            if client.poll() is not None:
                raise AssertionError(f'RDP client exited: {client.returncode}')
            geometry = root.get_geometry()
            raw = root.get_image(0, 0, geometry.width, geometry.height,
                                 X.ZPixmap, 0xffffffff)
            frame = Image.frombytes('RGB', (geometry.width, geometry.height),
                                    raw.data, 'raw', 'BGRX')
            mismatches = []
            # Browser toolbar height varies; samples stay far from boundaries.
            for y in ys:
                for x in xs:
                    quadrant = (0 if y < height//2 else 2) + (x >= width//2)
                    actual, expected = frame.getpixel((x, y)), colors[quadrant]
                    if any(abs(a-b) > 18 for a,b in zip(actual, expected)):
                        mismatches.append({'xy':[x,y], 'expected':expected,
                                           'actual':actual})
            if not mismatches:
                frame.save(out/'decoded.png')
                # Check actual RDP input as well as pixels after negotiation.
                for x, y in [(width//4, 180), (3*width//4, 180),
                             (width//4, height-80), (3*width//4, height-80)]:
                    original = frame.getpixel((x, y))
                    for expected in [(165,45,210), original]:
                        xtest.fake_input(screen, X.MotionNotify, x=x, y=y)
                        xtest.fake_input(screen, X.ButtonPress, 1)
                        xtest.fake_input(screen, X.ButtonRelease, 1)
                        screen.sync()
                        click_deadline = time.monotonic() + 8
                        while time.monotonic() < click_deadline:
                            pixel = root.get_image(x, y, 1, 1, X.ZPixmap, 0xffffffff)
                            actual = tuple(pixel.data[i] for i in [2,1,0])
                            if all(abs(a-b) <= 18 for a,b in zip(actual, expected)):
                                break
                            time.sleep(.1)
                        else:
                            raise AssertionError(f'RDP click missed target at {x},{y}: {actual}')
                print(json.dumps({'pass': True, 'size':[width,height],
                                  'checked_pixels':len(xs)*len(ys),
                                  'trusted_clicks':8}), flush=True)
                break
            time.sleep(.3)
        else:
            frame.save(out/'decoded-failed.png')
            (out/'mismatches.json').write_text(json.dumps(mismatches,indent=2))
            raise AssertionError(f'wrong decoded pixels: {mismatches[:3]}')
finally:
    if client and client.poll() is None:
        os.killpg(client.pid, signal.SIGTERM)
        try:
            client.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(client.pid, signal.SIGKILL)
            client.wait()
    screen.close()
