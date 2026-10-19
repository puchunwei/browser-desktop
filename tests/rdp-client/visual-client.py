"""Observe the RDP client's pixels and send a real mouse click through RDP."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from PIL import Image
from Xlib import X, display
from Xlib.ext import xtest
from cursor_probe import capture_cursor

host, port, phase = sys.argv[1:]
size = '1280x720' if phase == '1' else '640x1386'
out = Path('/evidence')
password = Path('/pw').read_text().strip()
args = [f'/v:{host}:{port}', '/u:' + os.environ.get('RDP_USER', 'browser'), f'/p:{password}',
        '/cert:ignore', f'/size:{size}', '/gfx', '/log-level:INFO']
screen = display.Display()
root = screen.screen().root
with (out / f'client-{phase}.log').open('w') as log:
    # Keep the password out of process arguments and shell tracing.
    client = subprocess.Popen(['xfreerdp3', '/args-from:stdin'], stdin=subprocess.PIPE,
                              stdout=log, stderr=subprocess.STDOUT, text=True,
                              start_new_session=True)
    client.stdin.write('\n'.join(args) + '\n')
    client.stdin.close()

    def capture():
        geometry = root.get_geometry()
        raw = root.get_image(0, 0, geometry.width, geometry.height, X.ZPixmap, 0xffffffff)
        return Image.frombytes('RGB', (geometry.width, geometry.height), raw.data, 'raw', 'BGRX')

    red, purple = (235, 52, 67), (165, 45, 210)
    before, after = (red, purple) if phase == '1' else (purple, red)
    colors = [before, (40, 190, 90), (35, 95, 220), (235, 185, 35)]

    def points(frame, color):
        # Sample rather than comparing compressed RDP colors byte for byte.
        return [(x, y) for y in range(0, frame.height, 8) for x in range(0, frame.width, 8)
                if all(abs(a - b) < 18 for a, b in zip(frame.getpixel((x, y)), color))]

    def wait_for_colors(expected):
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if client.poll() is not None:
                raise RuntimeError(f'RDP client exited with {client.returncode}')
            frame = capture()
            if all(len(points(frame, color)) > 150 for color in expected):
                return frame
            time.sleep(0.5)
        frame.save(out / f'failed-{phase}.png')
        raise RuntimeError('RDP client did not receive the browser test pattern')

    try:
        frame = wait_for_colors(colors)
        frame.save(out / f'desktop-{phase}.png')
        width, height = map(int, size.split('x'))
        edges = [point for color in colors for point in points(frame, color)]
        if (min(x for x, y in edges) > 8 or
                max(x for x, y in edges) < width - 12 or
                max(y for x, y in edges) < height - 12):
            raise RuntimeError(f'browser does not fill the {size} RDP desktop')
        # Check the actual client cursor: XGetImage alone omits it entirely.
        previous = None
        arrow_hash = None
        link_cursor = os.environ.get('EXPECTED_LINK_CURSOR', 'arrow')
        assert link_cursor in ('arrow', 'hand')
        # A newly attached viewer can show its own default arrow until the first
        # remote shape change. Visit text first so both compared images come
        # from the server, including when reconnecting over an existing arrow.
        text_pixels = points(frame, colors[2])
        xtest.fake_input(screen, X.MotionNotify,
                         x=sum(p[0] for p in text_pixels) // len(text_pixels),
                         y=sum(p[1] for p in text_pixels) // len(text_pixels))
        screen.sync()
        time.sleep(0.5)
        for name, color in zip(('arrow', 'hand', 'text'), colors[:3]):
            pixels = points(frame, color)
            cx = sum(p[0] for p in pixels) // len(pixels)
            cy = sum(p[1] for p in pixels) // len(pixels)
            xtest.fake_input(screen, X.MotionNotify, x=cx, y=cy)
            screen.sync()
            time.sleep(0.2)
            xtest.fake_input(screen, X.MotionNotify, x=cx + 2, y=cy)
            screen.sync()
            time.sleep(0.5)
            prefix = out / f'cursor-{phase}-{name}'
            stats = capture_cursor(screen, prefix, previous if name == 'text' or link_cursor == 'hand' else None)
            if stats['partial_alpha_pixels']:
                raise RuntimeError('legacy cursor unexpectedly uses partial alpha')
            if name == 'arrow':
                arrow_hash = stats['pixel_sha256']
            elif name == 'hand' and link_cursor == 'arrow' and stats['pixel_sha256'] != arrow_hash:
                raise RuntimeError('link cursor must retain the arrow image')
            previous = str(prefix) + '.json'
        pixels = points(frame, before)
        x = sum(p[0] for p in pixels) // len(pixels)
        y = sum(p[1] for p in pixels) // len(pixels)
        xtest.fake_input(screen, X.MotionNotify, x=x, y=y)
        xtest.fake_input(screen, X.ButtonPress, 1)
        xtest.fake_input(screen, X.ButtonRelease, 1)
        screen.sync()
        frame = wait_for_colors([after, *colors[1:]])
        frame.save(out / f'clicked-{phase}.png')
        print(f'OK: RDP desktop pixels and mouse input, connection {phase}', flush=True)
    finally:
        if client.poll() is None:
            os.killpg(client.pid, signal.SIGTERM)
        try:
            client.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(client.pid, signal.SIGKILL)
            client.wait()
        screen.close()
