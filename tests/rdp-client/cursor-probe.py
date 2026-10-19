"""Capture the real client cursor on a disposable RDP test display.

Call only against synthetic test desktops: the composited PNG includes the
client's entire screen. This probe opens no RDP/CDP connection and reads no
credentials. Imported callers retain ownership of their Display connection.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

from PIL import Image
from Xlib import X, display
from Xlib.ext import xfixes, xtest  # Register the XFIXES extension methods.


def capture_cursor(screen, output_prefix, assert_distinct_from=None):
    """Save cursor RGBA, a composited screen, and JSON; reject invalid shapes.

    ``assert_distinct_from`` names an earlier probe JSON to compare by pixels,
    rather than by serial number (which may change for identical images).
    Failure evidence is saved before raising RuntimeError.
    """
    if not screen.has_extension('XFIXES'):
        raise RuntimeError('XFIXES is unavailable on the client test display')
    screen.xfixes_query_version()
    screen.sync()
    root = screen.screen().root
    geometry = root.get_geometry()
    if geometry.depth not in (24, 32):
        raise RuntimeError('cursor probe requires a 24/32 bit client Xvfb screen')
    cursor = screen.xfixes_get_cursor_image(root)
    pixels = list(cursor.cursor_image)
    if not cursor.width or not cursor.height or len(pixels) != cursor.width * cursor.height:
        raise RuntimeError('XFixesGetCursorImage returned invalid cursor dimensions')

    rgba = bytearray()
    alphas = []
    for pixel in pixels:
        alpha = (pixel >> 24) & 255
        red, green, blue = (pixel >> 16) & 255, (pixel >> 8) & 255, pixel & 255
        # XFixes supplies premultiplied ARGB; Pillow expects straight RGBA.
        if 0 < alpha < 255:
            red, green, blue = (min(255, (channel * 255 + alpha // 2) // alpha)
                                for channel in (red, green, blue))
        elif alpha == 0:
            red = green = blue = 0
        rgba.extend((red, green, blue, alpha))
        alphas.append(alpha)
    image = Image.frombytes('RGBA', (cursor.width, cursor.height), bytes(rgba))
    stats = {
        'width': cursor.width, 'height': cursor.height,
        'x': cursor.x, 'y': cursor.y, 'xhot': cursor.xhot, 'yhot': cursor.yhot,
        'serial': cursor.cursor_serial,
        'transparent_pixels': alphas.count(0),
        'opaque_pixels': alphas.count(255),
        'visible_pixels': sum(alpha > 0 for alpha in alphas),
        'partial_alpha_pixels': sum(0 < alpha < 255 for alpha in alphas),
        'pixel_sha256': hashlib.sha256(bytes(rgba)).hexdigest(),
    }
    failures = []
    if stats['transparent_pixels'] == 0:
        failures.append('cursor has no transparent pixels')
    if stats['visible_pixels'] == 0:
        failures.append('cursor has no visible pixels')
    if assert_distinct_from is not None:
        previous = json.loads(Path(assert_distinct_from).read_text())
        if stats['pixel_sha256'] == previous['pixel_sha256']:
            failures.append('cursor pixels unchanged after the expected shape change')

    raw = root.get_image(0, 0, geometry.width, geometry.height, X.ZPixmap, 0xffffffff)
    if len(raw.data) != geometry.width * geometry.height * 4:
        raise RuntimeError('cursor probe requires an Xvfb screen with 32 bit pixel storage')
    desktop = Image.frombytes('RGB', (geometry.width, geometry.height), raw.data, 'raw', 'BGRX')
    desktop.paste(image, (cursor.x - cursor.xhot, cursor.y - cursor.yhot), image)
    prefix = Path(output_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(prefix) + '-cursor.png')
    desktop.save(str(prefix) + '-composited.png')
    stats.update(status='failed' if failures else 'passed', failures=failures)
    Path(str(prefix) + '.json').write_text(json.dumps(stats, indent=2) + '\n')
    if failures:
        raise RuntimeError('; '.join(failures))
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-prefix', required=True)
    parser.add_argument('--assert-distinct-from', help='previous probe JSON for another shape')
    parser.add_argument('--x', type=int, help='move the client pointer; requires --y')
    parser.add_argument('--y', type=int, help='move the client pointer; requires --x')
    parser.add_argument('--settle-ms', type=int, default=400, help='wait after pointer movement (0..5000)')
    args = parser.parse_args()
    if (args.x is None) != (args.y is None):
        parser.error('--x and --y must be supplied together')
    if not 0 <= args.settle_ms <= 5000:
        parser.error('--settle-ms must be between 0 and 5000')
    screen = display.Display()
    try:
        if args.x is not None:
            geometry = screen.screen().root.get_geometry()
            if not (0 <= args.x < geometry.width and 0 <= args.y < geometry.height):
                parser.error('pointer coordinates must be inside the client test screen')
            xtest.fake_input(screen, X.MotionNotify, x=args.x, y=args.y)
            screen.sync()
            time.sleep(args.settle_ms / 1000)
        stats = capture_cursor(screen, args.output_prefix, args.assert_distinct_from)
        print(json.dumps(stats, sort_keys=True))
    finally:
        screen.close()


if __name__ == '__main__':
    main()
