"""Regression: real RDP resize sent while display output is suppressed."""
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

out = Path('/evidence')
screen = display.Display()
root = screen.screen().root
host, port = sys.argv[1:3] if len(sys.argv) > 2 else ('127.0.0.1', '13390')
codec = sys.argv[3] if len(sys.argv) > 3 else 'basic'
assert codec in ('basic', 'avc420')
args = [f'/v:{host}:{port}', '/u:' + os.environ.get('RDP_USER', 'browser'), '/p:' + Path('/pw').read_text().strip(),
        '/cert:ignore', '/size:1280x720', '/dynamic-resolution',
        '-decorations', '/log-level:INFO']
args += ['/network:modem', '-gfx', '-rfx'] if codec == 'basic' else ['/network:lan', '/gfx:AVC420']
client = None
results = []
colors = [(235, 52, 67), (40, 190, 90), (35, 95, 220), (235, 185, 35)]

def capture():
    g = root.get_geometry()
    raw = root.get_image(0, 0, g.width, g.height, X.ZPixmap, 0xffffffff)
    return Image.frombytes('RGB', (g.width, g.height), raw.data, 'raw', 'BGRX')

def points(frame, color):
    # The basic bitmap path uses lossy JPEG; keep distinct target colors farther
    # apart than twice this tolerance. Extents and trusted clicks are asserted too.
    # Exclude browser chrome: existing tab favicons can share a target color.
    return [(x,y) for y in range(128,frame.height,8) for x in range(0,frame.width,8)
            if all(abs(a-b)<40 for a,b in zip(frame.getpixel((x,y)),color))]

def wait_pattern(label, width, height):
    deadline = time.monotonic() + 18
    while time.monotonic() < deadline:
        if client.poll() is not None:
            raise RuntimeError('RDP client exited')
        frame = capture()
        positions = [points(frame, color) for color in colors]
        if all(len(p)>100 for p in positions):
            all_points = [p for group in positions for p in group]
            actual = (max(x for x,y in all_points), max(y for x,y in all_points))
            if width-14 <= actual[0] <= width+8 and height-14 <= actual[1] <= height+8:
                frame.save(out/f'{label}.png')
                print(json.dumps({'phase':label,'requested':[width,height],'observed':actual}),flush=True)
                return frame, positions
        time.sleep(.2)
    frame.save(out/f'{label}-failed.png')
    raise AssertionError(f'{label}: browser pixels did not follow requested {width}x{height}; observed {actual if "actual" in locals() else "no complete pattern"}')

def check_clicks(label, frame, positions):
    clicks = []
    for color, group in zip(colors, positions):
        # Stay off the centered label: glyph antialiasing can change on toggling.
        cx = min(x for x,y in group) + (max(x for x,y in group)-min(x for x,y in group)) / 4
        cy = min(y for x,y in group) + (max(y for x,y in group)-min(y for x,y in group)) / 4
        x,y = min(group, key=lambda p: (p[0]-cx)**2 + (p[1]-cy)**2)
        for expected in [(165,45,210), color]:
            xtest.fake_input(screen,X.MotionNotify,x=x,y=y)
            xtest.fake_input(screen,X.ButtonPress,1)
            xtest.fake_input(screen,X.ButtonRelease,1)
            screen.sync()
            deadline = time.monotonic()+6
            while time.monotonic()<deadline:
                if all(abs(a-b)<40 for a,b in zip(capture().getpixel((x,y)),expected)):
                    break
                time.sleep(.1)
            else:
                capture().save(out/f'{label}-click-failed.png')
                raise AssertionError(f'{label}: real RDP click missed target at {x},{y}')
            clicks.append([x,y])
    print(json.dumps({'phase':label,'trusted_pointer_clicks':len(clicks),'positions':clicks}),flush=True)
    return len(clicks)

try:
    with (out/'freerdp.log').open('w') as log:
        client = subprocess.Popen(['xfreerdp3','/args-from:stdin'],stdin=subprocess.PIPE,
            stdout=log,stderr=subprocess.STDOUT,text=True,start_new_session=True)
        client.stdin.write('\n'.join(args)+'\n');client.stdin.close()
        frame,positions=wait_pattern('initial',1280,720)
        check_clicks('initial',frame,positions)
        windows=[w for w in root.query_tree().children if any('freerdp' in str(v).lower() for v in (w.get_wm_class() or []))]
        assert len(windows)==1
        window=windows[0]
        for index,(width,height,suppress) in enumerate([(640,1386,True),(1280,720,True),(640,1386,False),(1280,720,False)]):
            if suppress:
                window.unmap();screen.sync();time.sleep(.4)
            window.configure(x=0,y=0,width=width,height=height);screen.sync()
            time.sleep(1.2)
            if suppress:
                window.map();screen.sync()
            frame,positions=wait_pattern(f'rotation-{index+1}',width,height)
            clicks=check_clicks(f'rotation-{index+1}',frame,positions)
            results.append({'rotation':index+1,'width':width,'height':height,'suppressed':suppress,'trusted_pointer_clicks':clicks})
        print('PASS: same RDP connection follows repeated rotations and real target clicks including suppressed output',flush=True)
finally:
    (out/'rotation-results.json').write_text(json.dumps(results,indent=2)+'\n')
    if client and client.poll() is None:
        os.killpg(client.pid,signal.SIGTERM)
        try:client.wait(timeout=5)
        except subprocess.TimeoutExpired:os.killpg(client.pid,signal.SIGKILL);client.wait()
    screen.close()
