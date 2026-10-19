"""Provide the classic arrow for link cursors, without changing text/resize cursors.

Only the hand aliases exist in this theme. Leaving left_ptr absent lets Chromium
fall back to its core font for all other standard shapes instead of substituting
an arrow for missing text or resize images. The bitmap matches the classic X11
arrow already used by this deployment; it has no partial alpha or shadow.
"""
from pathlib import Path
import struct

shape = [
    'ww', 'w#w', 'w##w', 'w###w', 'w####w', 'w#####w', 'w######w',
    'w#######w', 'w########w', 'w#####wwww', 'w##w##w', 'w#w.w##w',
    'ww..w##w', '.....w##w', '.....w##w', '......ww',
]
colors = {'.': 0, '#': 0xff000000, 'w': 0xffffffff}
pixels = [colors[c] for row in shape + [''] * 16 for c in row.ljust(32, '.')]
image_type = 0xfffd0002
# Xcursor file header, one table-of-contents entry, one ARGB image chunk.
header = struct.pack('<4I', 0x72756358, 16, 0x10000, 1)
toc = struct.pack('<3I', image_type, 32, 28)
chunk = struct.pack('<9I', 36, image_type, 32, 1, 32, 32, 1, 1, 0)
data = header + toc + chunk + struct.pack('<1024I', *pixels)
directory = Path('/usr/local/share/browser-cursors/default/cursors')
directory.mkdir(parents=True, exist_ok=True)
for name in ('pointer', 'hand1', 'hand2', 'pointing_hand'):
    (directory / name).write_bytes(data)
