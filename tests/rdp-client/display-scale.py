"""Real negotiated density, stable live Chrome and trusted pointer regression.

Runs only inside the disposable client started by display-scale-image.sh.
CDP observes synthetic page state; pointer and menu input travel through RDP.
"""
import json
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request

from PIL import Image, ImageChops, ImageStat
import websocket
from Xlib import X, XK, display
from Xlib.ext import xtest

host, port, cdp_port = sys.argv[1:4]
out = Path('/evidence')
base = f'http://{host}:{cdp_port}'
screen = display.Display()
root = screen.screen().root
client = None
results = []
sequence = 0
identity = None
sockets = {}
command_id = 0
transition_started = None
network_before = dict(received=0, sent=0)


def rdp_network_bytes():
    # Linux INET_DIAG_INFO / TCP_INFO counts only this disposable RDP socket,
    # avoiding CDP and unrelated traffic in the shared host network namespace.
    netlink = socket.socket(socket.AF_NETLINK, socket.SOCK_DGRAM, 4)
    netlink.settimeout(3)
    try:
        request = struct.pack('=BBBBI', socket.AF_INET, 6, 2, 0, 0xffffffff) + bytes(48)
        netlink.sendto(struct.pack('=IHHII', 16+len(request), 20, 0x301, 1, 0) + request, (0,0))
        matches = []
        while True:
            packet = netlink.recv(65536)
            offset = 0
            while offset < len(packet):
                length, kind, _, _, _ = struct.unpack_from('=IHHII', packet, offset)
                assert length >= 16
                message = packet[offset+16:offset+length]
                offset += (length+3) & ~3
                if kind == 3:
                    assert len(matches) == 1, f'Expected one disposable RDP TCP socket: {len(matches)}'
                    return matches[0]
                if kind != 20 or struct.unpack_from('!H',message,6)[0] != int(port):
                    continue
                position = 72
                while position+4 <= len(message):
                    size, attribute = struct.unpack_from('=HH',message,position)
                    assert size >= 4
                    value = message[position+4:position+size]
                    position += (size+3) & ~3
                    if attribute == 2:
                        # Stable Linux TCP_INFO fields: bytes_received / bytes_sent.
                        matches.append(dict(received=struct.unpack_from('=Q',value,128)[0],
                                            sent=struct.unpack_from('=Q',value,200)[0]))
    finally:
        netlink.close()


def http(path):
    with urllib.request.urlopen(base + path, timeout=5) as response:
        return json.load(response)


def call(url, method, params=None):
    global command_id
    ws = sockets.get(url)
    if ws is None:
        ws = sockets[url] = websocket.create_connection(url, timeout=10, suppress_origin=True)
    command_id += 1
    request_id = command_id
    started = time.monotonic()
    try:
        ws.send(json.dumps(dict(id=request_id, method=method, params=params or {})))
        while True:
            reply = json.loads(ws.recv())
            if reply.get('id') == request_id:
                assert 'error' not in reply, reply
                return reply.get('result', {})
    finally:
        with (out / 'cdp-commands.jsonl').open('a') as log:
            log.write(json.dumps(dict(method=method, target=url.rsplit('/',1)[-1],
                                     elapsed=round(time.monotonic()-started,3)))+'\n')


browser = http('/json/version')['webSocketDebuggerUrl']
html = '''<meta charset="utf-8"><title>Density regression</title>
<style>body{margin:0;font:18px sans-serif;background:#fff;color:#111}
header{position:fixed;inset:0 0 auto;background:#e7efff;height:96px;z-index:1}
button{position:absolute;right:8px;top:8px;width:100px;height:48px;background:#eb3443;border:0}
textarea{width:200px;height:40px;margin:4px;caret-color:transparent}
main{padding-top:104px;height:6000px}p{margin:12px}</style>
<header><div style="position:absolute;top:64px">Chinese 中文清晰度 / English 0123456789</div><textarea id="draft"></textarea><button id="click">Click</button></header>
<main><p>Chinese 中文清晰度 / English text 0123456789</p>
<p style="background:#222;color:#fff">Stationary text 静态文字</p></main>
<script>window.pageToken=String(Date.now())+String(Math.random());window.clicks=0;
click.onpointerdown=e=>{if(e.isTrusted){window.clicks++;window.lastClick=[e.clientX,e.clientY];}};
draft.value='English draft 中文草稿';scrollTo(0,420);</script>'''
target = call(browser, 'Target.createTarget', {'url': 'data:text/html,' + urllib.parse.quote(html)})['targetId']
call(browser, 'Target.activateTarget', {'targetId': target})
window = call(browser, 'Browser.getWindowForTarget', {'targetId': target})['windowId']
call(browser, 'Browser.setWindowBounds', {'windowId': window, 'bounds': {'windowState': 'maximized'}})
page = next(p['webSocketDebuggerUrl'] for p in http('/json/list') if p['id'] == target)


def evaluate(expression):
    reply = call(page, 'Runtime.evaluate', {'expression': expression, 'returnByValue': True})
    assert 'exceptionDetails' not in reply, reply
    return reply['result'].get('value')


def metrics():
    return evaluate('''(()=>{let r=click.getBoundingClientRect();return {
    dpr:devicePixelRatio,screen:[screen.width,screen.height],inner:[innerWidth,innerHeight],
    outer:[outerWidth,outerHeight],token:pageToken,draft:draft.value,scroll:scrollY,
    navigation:performance.timeOrigin,clicks:window.clicks,
    target:[r.x,r.y,r.width,r.height],zoom:visualViewport.scale}})()''')


def command(action):
    global sequence
    sequence += 1
    request = out / 'request'
    temporary = out / 'request.tmp'
    temporary.write_text(f'{sequence} {action}\n')
    temporary.replace(request)
    response = out / f'response-{sequence}.json'
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if response.exists():
            value = json.loads(response.read_text())
            assert not value.get('error'), value
            return value
        time.sleep(.1)
    raise AssertionError(f'host action timed out: {action}')


def capture():
    windows = [w for w in root.query_tree().children if 'freerdp' in str(w.get_wm_class()).lower()]
    g = windows[0].get_geometry() if windows else root.get_geometry()
    raw = root.get_image(0, 0, g.width, g.height, X.ZPixmap, 0xffffffff)
    return Image.frombytes('RGB', (g.width, g.height), raw.data, 'raw', 'BGRX')


def key(name, down=True):
    xtest.fake_input(screen, X.KeyPress if down else X.KeyRelease,
                     screen.keysym_to_keycode(XK.string_to_keysym(name)))
    screen.sync()


def tap(name):
    key(name)
    key(name, False)
    time.sleep(.12)


def scale_menu(label):
    before = capture()
    key('Control_L'); key('Alt_L'); tap('s'); key('Alt_L', False); key('Control_L', False)
    time.sleep(.4)
    after = capture()
    box = ImageChops.difference(before, after).getbbox()
    assert box, 'Desktop scale menu did not become visible'
    scale = metrics()['dpr']
    left,top,right,bottom = box
    windows = [w for w in root.query_tree().children if 'freerdp' in str(w.get_wm_class()).lower()]
    assert len(windows) == 1
    geometry = windows[0].get_geometry()
    assert 0 <= left < right <= geometry.width and 0 <= top < bottom <= geometry.height, box
    assert (bottom-top)/5 >= 12*scale, f'Menu rows did not scale with density: {box}, {scale}'
    (out / f'{label}-menu-geometry.json').write_text(json.dumps(
        dict(box=box, width=right-left, height=bottom-top, row_height=(bottom-top)/5, scale=scale)))
    after.save(out / f'{label}-menu.png')
    after.crop(box).save(out / f'{label}-menu-crop.png')
    return box


def preset(value):
    global transition_started
    transition_started = time.monotonic()
    scale_menu(f'menu-{sequence}-{value}')
    tap('Home')
    for _ in range(['auto', '100', '150', '200', '300'].index(str(value))):
        tap('Down')
    tap('Return')


def pointer_preset(label, value):
    global transition_started
    transition_started = time.monotonic()
    box = scale_menu(label)
    index = ['auto','100','150','200','300'].index(str(value))
    left,top,right,bottom = box
    xtest.fake_input(screen, X.MotionNotify, x=(left+right)//2,
                     y=round(top+(index+.5)*(bottom-top)/5))
    xtest.fake_input(screen, X.ButtonPress,1)
    xtest.fake_input(screen, X.ButtonRelease,1)
    screen.sync()
    return box


def stop():
    global client
    if client and client.poll() is None:
        os.killpg(client.pid, signal.SIGTERM)
        try:
            client.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(client.pid, signal.SIGKILL)
            client.wait()
    client = None
    time.sleep(.4)


def connect(label, size, scale, hint, dynamic=False):
    global client, transition_started, network_before
    transition_started = time.monotonic()
    network_before = dict(received=0, sent=0)
    stop()
    width, height = size
    args = [f'/v:{host}:{port}', '/u:browser', '/p:' + Path('/pw').read_text().strip(),
            '/cert:ignore', f'/size:{width}x{height}', '/bpp:32',
            '/network:modem', '/cache:bitmap:off',
            '-decorations', '/log-level:INFO']
    if dynamic:
        args += ['/dynamic-resolution']
    if scale is not None:
        args += [f'/scale-desktop:{scale}', '/scale-device:100']
    if hint:
        args += [f'/client-hostname:{hint}']
    args += ['-gfx', '-rfx', '-nsc', '/tune:FreeRDP_SupportGraphicsPipeline:FALSE,FreeRDP_RemoteFxCodec:FALSE,FreeRDP_NSCodec:FALSE']
    (out / f'{label}-client-options.json').write_text(json.dumps([
        arg if not arg.startswith('/p:') else '/p:<redacted>' for arg in args], indent=2)+'\n')
    with (out / f'{label}-freerdp.log').open('w') as log:
        client = subprocess.Popen(['xfreerdp3', '/args-from:stdin'], stdin=subprocess.PIPE,
                                  stdout=log, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    client.stdin.write('\n'.join(args) + '\n')
    client.stdin.close()
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        assert client.poll() is None, f'{label}: RDP exited before viewer window mapped'
        windows=[w for w in root.query_tree().children if 'freerdp' in str(w.get_wm_class()).lower() and w.get_attributes().map_state==X.IsViewable]
        if len(windows)==1:
            g=windows[0].get_geometry()
            if (g.width,g.height)==size:
                break
        time.sleep(.1)
    else:
        raise AssertionError(f'{label}: intended viewer window did not map')


def check(label, size, scale, source=None, compare=False):
    global identity, transition_started, network_before
    started = transition_started or time.monotonic()
    width, height = size
    expected = [round(width * 100 / scale), round(height * 100 / scale)]
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        assert client.poll() is None, f'{label}: RDP client exited'
        value = metrics()
        # Both screen and actual layout must settle, including Chrome's window minimum.
        if (value['dpr'] == scale / 100 and
                all(abs(a-b) <= 1 for a,b in zip(value['screen'], expected)) and
                abs(value['inner'][0] - expected[0]) <= 1):
            break
        time.sleep(.2)
    else:
        command('snapshot ' + label + '-failed')
        capture().save(out / f'{label}-failed.png')
        raise AssertionError(f'{label}: density/layout/clipping: expected {scale}% {expected}, got {value}')
    layout_seconds = time.monotonic() - started
    assert value['zoom'] == 1, value
    assert 60 <= value['outer'][1] - value['inner'][1] <= 115, value
    current_identity = [value[k] for k in ['token', 'navigation', 'draft', 'scroll']]
    if identity is None:
        identity = current_identity
    assert current_identity == identity, (label, identity, current_identity)
    # Click at measured physical RDP coordinates, then inspect event.isTrusted state.
    x,y,w,h = value['target']
    px,py = round((x+w/2)*scale/100), round((y+h/2 + value['outer'][1]-value['inner'][1])*scale/100)
    assert client.poll() is None, f'{label}: RDP client exited before click'
    windows = [w for w in root.query_tree().children if 'freerdp' in str(w.get_wm_class()).lower()]
    deadline=time.monotonic()+10
    while len(windows)!=1 and time.monotonic()<deadline:
        time.sleep(.1)
        windows=[w for w in root.query_tree().children if 'freerdp' in str(w.get_wm_class()).lower() and w.get_attributes().map_state==X.IsViewable]
    assert len(windows) == 1, 'Expected one disposable viewer window'
    windows[0].configure(x=0,y=0,stack_mode=X.Above)
    windows[0].set_input_focus(X.RevertToParent,X.CurrentTime)
    screen.sync()
    # CDP layout can settle before the RDP frame reaches the viewer. Gate pixels too.
    sample = (round((x+8)*scale/100), round((y+8+value['outer'][1]-value['inner'][1])*scale/100))
    deadline = time.monotonic()+15
    while time.monotonic()<deadline:
        pixel = capture().getpixel(sample)
        if pixel[0]>180 and pixel[1]<100 and pixel[2]<120:
            break
        time.sleep(.2)
    else:
        capture().save(out/f'{label}-unsettled.png')
        print(f'{label}: RDP viewer incomplete at {sample}: {pixel}',flush=True)
        command('snapshot viewer-failed')
        raise AssertionError(f'{label}: viewer pixels did not reach the measured target: {sample} {pixel}')
    before = metrics()['clicks']
    clicked = time.monotonic()
    xtest.fake_input(screen, X.MotionNotify, x=px, y=py)
    xtest.fake_input(screen, X.ButtonPress, 1)
    xtest.fake_input(screen, X.ButtonRelease, 1)
    screen.sync()
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and metrics()['clicks'] != before + 1:
        time.sleep(.1)
    assert metrics()['clicks'] == before + 1, f'{label}: trusted RDP click missed {px},{py}'
    click_seconds = time.monotonic() - clicked
    # Cursor away; caret hidden; no wall clocks or animated content in text crops.
    xtest.fake_input(screen, X.MotionNotify, x=width-2, y=height-2); screen.sync()
    time.sleep(.5)
    host_value = command('snapshot ' + label)
    if source:
        assert host_value['status']['source'] == source, host_value
    assert host_value['status']['scale'] == scale, host_value
    assert host_value['status']['geometry'] == list(size), host_value
    assert host_value['window_pixels'] == list(size), host_value
    image = capture().crop((0, 0, width, height))
    image.save(out / f'{label}-decoded.png')
    comparison = None
    if compare:
        # Confirm the stationary decoded frame has settled before measuring loss.
        time.sleep(2)
        repeated = capture().crop((0,0,width,height))
        repeated.save(out / f'{label}-decoded-repeat.png')
        stable = ImageChops.difference(image,repeated).getbbox() is None
        assert stable, f'{label}: decoded frame did not settle for quality comparison'
        source_image = Image.open(out / f'{label}-source.ppm').convert('RGB')
        source_image.save(out / f'{label}-source.png')
        # Compare identical physical pixels, at matched logical geometry. Exclude cursor.
        box = (8, 8, width-8, min(height-8, round(190*scale/100)))
        a,b = source_image.crop(box), image.crop(box)
        diff = ImageChops.difference(a,b)
        count = sum(1 for pixel in diff.getdata() if pixel != (0,0,0))
        comparison = dict(box=box, compared=a.width*a.height, differing=count,
                          mean_absolute_rgb_error=ImageStat.Stat(diff).mean, decoded_stable_seconds=2)
        assert count == 0, f'{label}: legacy decoded text differs: {comparison}'
    if results:
        host_value['network_delta'] = {k:host_value['network_bytes'][k]-results[-1]['host']['network_bytes'][k] for k in ('rx','tx')}
    network_now = rdp_network_bytes()
    network_delta = {key:network_now[key]-network_before[key] for key in network_now}
    network_before = network_now
    result = dict(phase=label, pixels=size, scale=scale, metrics=value, host=host_value,
                  client_rdp_bytes=network_now, client_rdp_delta_bytes=network_delta,
                  settle_seconds=round(layout_seconds,3), evidence_seconds=round(time.monotonic()-started,3), click_seconds=round(click_seconds,3),
                  pixel_comparison=comparison)
    results.append(result)
    (out/'result.json').write_text(json.dumps(results, indent=2)+'\n')
    print(json.dumps(result), flush=True)
    transition_started = None
    return value


def toolbar(label, size, scale):
    # Exercise Chrome's own omnibox and overflow menu at the native phone width.
    # Input travels through RDP; CDP observes only focus/page identity.
    key('Control_L'); tap('l'); key('Control_L', False)
    time.sleep(.3)
    assert evaluate('document.hasFocus()') is False, 'Chrome address bar did not take focus'
    capture().save(out / f'{label}-address-bar.png')
    tap('Escape')
    before = capture()
    xtest.fake_input(screen, X.MotionNotify, x=size[0]-round(18*scale/100),
                     y=round(63*scale/100))
    xtest.fake_input(screen, X.ButtonPress,1)
    xtest.fake_input(screen, X.ButtonRelease,1)
    screen.sync()
    time.sleep(.5)
    after = capture()
    after.save(out / f'{label}-chrome-menu.png')
    difference = ImageChops.difference(before, after)
    # Menu pixels must extend below the toolbar; omnibox focus alone cannot pass.
    changed = sum(1 for pixel in difference.crop((0,round(90*scale/100),
                  size[0],min(size[1],round(650*scale/100)))).getdata() if pixel != (0,0,0))
    assert changed > 10000, f'{label}: Chrome menu did not open at right toolbar edge'
    tap('Escape')


def reconnect(label, size, scale):
    connect(label, size, scale, 'test-mac' if label.startswith('mac-') else
            'test-phone-native' if 'native' in label else 'test-phone')
    return check(label, size, scale)


def resize(label, size, scale):
    global transition_started
    transition_started = time.monotonic()
    windows = [w for w in root.query_tree().children
               if 'freerdp' in str(w.get_wm_class()).lower() and
               w.get_attributes().map_state == X.IsViewable]
    assert len(windows) == 1
    windows[0].configure(x=0, y=0, width=size[0], height=size[1])
    screen.sync()
    try:
        return check(label, size, scale)
    except Exception:
        capture().save(out / f'{label}-failed.png')
        command('snapshot ' + label + '-failed')
        raise


try:
    # The baseline mode makes the same behavioral assertion and is expected to fail.
    if os.environ.get('DENSITY_BASELINE') == '1':
        connect('baseline', (2048,1536), 200, 'test-baseline')
        check('baseline', (2048,1536), 200)
    else:
        connect('mac-100', (3008,1692), 100, 'test-mac')
        check('mac-100', (3008,1692), 100, 'negotiated', True)
        connect('mac-retina', (6016,3384), 200, 'test-mac')
        check('mac-retina', (6016,3384), 200, 'negotiated', True)
        reconnect('mac-small-retina', (2048,1536), 200)
        reconnect('mac-full-retina', (6016,3384), 200)
        connect('phone-portrait', (640,1386), 100, 'test-phone')
        check('phone-portrait', (640,1386), 100)
        reconnect('phone-landscape', (1386,640), 100)
        preset(150)
        check('phone-larger', (1386,640), 150, 'manual')
        connect('phone-remembered', (1386,640), 100, 'test-phone')
        check('phone-remembered', (1386,640), 150, 'manual')
        pointer_preset('phone-menu-150','auto')
        check('phone-auto', (1386,640), 100, 'negotiated')
        connect('phone-native', (1170,2532), 300, 'test-phone-native')
        check('phone-native', (1170,2532), 300, 'negotiated')
        toolbar('phone-native', (1170,2532), 300)
        check('phone-native-toolbar', (1170,2532), 300, 'negotiated')
        pointer_preset('native-menu-300', 200)
        check('native-menu-200-selected', (1170,2532), 200, 'manual')
        pointer_preset('native-menu-200', 'auto')
        check('native-menu-auto-selected', (1170,2532), 300, 'negotiated')
        reconnect('phone-native-landscape', (2532,1170), 300)
        reconnect('phone-native-portrait', (1170,2532), 300)
        command('recover')
        check('controller-recovered', (1170,2532), 300)
        # A new client hint must not inherit another client's override. Omitting
        # scale options still sends FreeRDP's valid default 100% metadata.
        connect('unknown-client', (1280,960), None, 'test-unknown')
        check('unknown-client', (1280,960), 100, 'negotiated', True)
        connect('mac-return', (3008,1692), 100, 'test-mac')
        check('mac-return', (3008,1692), 100, 'negotiated')
        scale_menu('mac-return-100')
        tap('Escape')
        # Debian's pinned FreeRDP planar context retains its initial maximum.
        # Exercise live growth with server bitmap compression disabled; fixed
        # reconnects above still require exact compressed legacy pixels.
        command('bitmap-live')
        if os.environ.get('DENSITY_FIXED_ONLY') != '1':
            connect('live-mac', (6016,3384), 200, 'test-mac', dynamic=True)
            check('live-mac', (6016,3384), 200)
            resize('live-mac-small', (2048,1536), 200)
            resize('live-mac-full', (6016,3384), 200)
            connect('live-phone', (640,1386), 100, 'test-phone', dynamic=True)
            check('live-phone', (640,1386), 100)
            resize('live-phone-landscape', (1386,640), 100)
            resize('live-phone-portrait', (640,1386), 100)
            connect('live-native', (1170,2532), 300, 'test-phone-native', dynamic=True)
            check('live-native', (1170,2532), 300)
            resize('live-native-landscape', (2532,1170), 300)
            resize('live-native-portrait', (1170,2532), 300)
        print('PASS: negotiated density, real clicks/menu, stable page and per-client preferences', flush=True)
except Exception:
    if client:
        try: command('snapshot final-failure')
        except Exception: pass
        probes=[]
        for url,method,params in (
                (browser,'Target.getTargets',{}),
                (browser,'Browser.getWindowBounds',{'windowId':window}),
                (page,'Runtime.evaluate',{'expression':'[document.hasFocus(),innerWidth,innerHeight]', 'returnByValue':True})):
            try:
                probe=websocket.create_connection(url,timeout=3,suppress_origin=True)
                probe.send(json.dumps(dict(id=1,method=method,params=params)))
                probes.append(dict(method=method,reply=json.loads(probe.recv())))
                probe.close()
            except Exception as error:
                probes.append(dict(method=method,error=repr(error)))
        (out/'failure-probes.json').write_text(json.dumps(probes,indent=2))
        try:
            capture().save(out/'failure-before-menu.png')
            tap('Escape')
            key('Control_L'); key('Alt_L'); tap('s'); key('Alt_L',False); key('Control_L',False)
            time.sleep(.5)
            capture().save(out/'failure-rdp-menu.png')
        except Exception: pass
    raise
finally:
    if client:
        try: capture().save(out/'last-frame.png')
        except Exception: pass
    stop()
    try:
        call(browser, 'Target.closeTarget', {'targetId': target})
    finally:
        for ws in sockets.values():
            ws.close()
    screen.close()
