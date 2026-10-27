#!/usr/bin/env python3
"""Session-owned XSettings and bounded, credential-checked local density control."""
import argparse
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import signal
import socket
import struct
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

SOCKET = '/run/xrdp/display-scale/control.sock'
RUNTIME = Path('/run/browser-desktop')
MAX_EVENT = 4096
PRESETS = {'100', '150', '200', '300'}
KEY = re.compile(r'[0-9a-f]{64}')


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def valid_pair(desktop, device):
    return integer(desktop, 100, 500) and type(device) is int and device in (100, 140, 180)


def read_json(path):
    try:
        with path.open('rb') as stream:
            data = stream.read(65537)
        return json.loads(data) if len(data) <= 65536 else None
    except (OSError, ValueError, RecursionError):
        return None


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.new')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, separators=(',', ':'))
    os.replace(temporary, path)


class Policy:
    def __init__(self, preferences, state, apply, worker_lookup=None):
        self.worker_lookup = worker_lookup or worker_birth
        self.preferences, self.state, self.apply = preferences, state, apply
        saved = read_json(preferences)
        self.preferences_map = saved if (isinstance(saved, dict) and len(saved) <= 256 and
            all(KEY.fullmatch(k) and type(v) is int and str(v) in PRESETS for k, v in saved.items())) else {}
        self.current = dict(pid=0, birth=0, key='', desktop=100, source='default', override=None, geometry=[0, 0])
        saved = read_json(state)
        if (isinstance(saved, dict) and set(saved) == set(self.current) and
                integer(saved['pid'], 0, 2147483647) and integer(saved['birth'], 0, 2**63 - 1) and
                isinstance(saved['key'], str) and
                (saved['key'] == '' or KEY.fullmatch(saved['key'])) and
                integer(saved['desktop'], 100, 500) and
                saved['source'] in ('default', 'negotiated', 'monitor', 'mixed-monitors', 'invalid-monitors') and
                (saved['override'] is None or (type(saved['override']) is int and str(saved['override']) in PRESETS)) and
                isinstance(saved['geometry'], list) and len(saved['geometry']) == 2 and
                all(integer(n, 0, 32768) for n in saved['geometry']) and
                saved['birth'] > 0 and self.worker_lookup(saved['pid']) == saved['birth']):
            self.current = saved
        self.last_scale = None
        self.sync()

    def status(self):
        return dict(scale=self.current['override'] or self.current['desktop'],
                    source='manual' if self.current['override'] else self.current['source'],
                    geometry=self.current['geometry'])

    def sync(self):
        scale = self.status()['scale']
        if scale != self.last_scale:
            self.apply(scale)
            self.last_scale = scale
        atomic_json(self.state, self.current)

    def expire_worker(self):
        if self.current['pid'] and self.worker_lookup(self.current['pid']) != self.current['birth']:
            self.current = dict(pid=0, birth=0, key='', desktop=100, source='default', override=None, geometry=[0, 0])
            self.sync()

    def event(self, event, pid, birth=0):
        self.expire_worker()
        same_worker = (pid, birth) == (self.current['pid'], self.current['birth'])
        if event['kind'] == 'resize' and not same_worker and self.current['pid']:
            return
        hint = bytes.fromhex(event['hint'])
        key = hashlib.sha256(hint + b'\0' + json.dumps(event['os']).encode()).hexdigest() if hint else ''
        if not same_worker or (event['kind'] == 'connect' and key != self.current['key']):
            self.current.update(pid=pid, birth=birth, key=key, override=self.preferences_map.get(key))
        desktop, source = (event['desktop'], 'negotiated') if valid_pair(event['desktop'], event['device']) else (100, 'default')
        monitors = event['monitors']
        if monitors and any(pair != [0, 0] for pair in monitors):
            if not all(valid_pair(*pair) for pair in monitors):
                desktop, source = 100, 'invalid-monitors'
            elif len({pair[0] for pair in monitors}) != 1:
                desktop, source = 100, 'mixed-monitors'
            else:
                desktop, source = monitors[0][0], 'monitor'
        self.current.update(desktop=desktop, source=source, geometry=[event['width'], event['height']])
        self.sync()

    def set(self, value):
        if value != 'auto' and value not in PRESETS:
            raise ValueError('invalid preset')
        self.expire_worker()
        override = None if value == 'auto' else int(value)
        key = self.current['key']
        if key:
            self.preferences_map.pop(key, None)
            if override:
                if len(self.preferences_map) >= 256:
                    self.preferences_map.pop(next(iter(self.preferences_map)))
                self.preferences_map[key] = override
            atomic_json(self.preferences, self.preferences_map)
        self.current['override'] = override
        self.sync()


def dispatch(policy, data, uid, pid, desktop_uid, xrdp_uid, birth=0):
    """Return sanitized replies; silently discard malformed/unauthorized datagrams."""
    if len(data) > MAX_EVENT:
        return None
    try:
        event = json.loads(data)
        if not isinstance(event, dict):
            return None
        op = event.get('op')
        if op == 'event':
            if uid != xrdp_uid or set(event) != {'op', 'kind', 'desktop', 'device', 'hint', 'os', 'width', 'height', 'monitors'}:
                return None
            if (event['kind'] not in ('connect', 'resize') or
                    not all(integer(event[n], 0, 4294967295) for n in ('desktop', 'device')) or
                    not all(integer(event[n], 1, 32768) for n in ('width', 'height')) or
                    not isinstance(event['hint'], str) or len(event['hint']) > 512 or
                    not re.fullmatch(r'(?:[0-9a-f]{2})*', event['hint']) or
                    not isinstance(event['os'], list) or len(event['os']) != 2 or
                    not all(integer(n, 0, 65535) for n in event['os']) or
                    not isinstance(event['monitors'], list) or len(event['monitors']) > 16 or
                    not all(isinstance(pair, list) and len(pair) == 2 and
                            all(integer(n, 0, 4294967295) for n in pair) for pair in event['monitors'])):
                return None
            policy.event(event, pid, birth)
        elif uid in (desktop_uid, 0):
            if op == 'set' and set(event) == {'op', 'value'} and isinstance(event['value'], str):
                policy.set(event['value'])
            elif op != 'status' or set(event) != {'op'}:
                return None
        else:
            return None
        return policy.status()
    except (ValueError, TypeError, KeyError, RecursionError):
        return None


def settings(scale):
    # Fractional density uses integer GDK window scale with fractional unscaled DPI.
    factor = max(1, scale // 100)
    dpi = round(96 * 1024 * scale / 100)
    return (f'Xft/DPI {dpi}\nGdk/WindowScalingFactor {factor}\n'
            f'Gdk/UnscaledDPI {round(dpi / factor)}\n'
            f'Gtk/CursorThemeSize {round(24 * scale / 100)}\n')


def selection_ready():
    """Check that an XSettings owner exists before allowing Chrome to start."""
    x = ctypes.CDLL('libX11.so.6')
    x.XOpenDisplay.argtypes, x.XOpenDisplay.restype = [ctypes.c_char_p], ctypes.c_void_p
    x.XDefaultScreen.argtypes, x.XDefaultScreen.restype = [ctypes.c_void_p], ctypes.c_int
    x.XInternAtom.argtypes, x.XInternAtom.restype = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int], ctypes.c_ulong
    x.XGetSelectionOwner.argtypes, x.XGetSelectionOwner.restype = [ctypes.c_void_p, ctypes.c_ulong], ctypes.c_ulong
    x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    display = x.XOpenDisplay(None)
    if not display:
        return False
    try:
        name = f'_XSETTINGS_S{x.XDefaultScreen(display)}'.encode()
        return bool(x.XGetSelectionOwner(display, x.XInternAtom(display, name, 0)))
    finally:
        x.XCloseDisplay(display)


def child_guard(parent_pid):
    # A SIGKILLed controller must not leave an unmanaged XSettings owner behind.
    # The controller is single-threaded; this runs in the child before exec.
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    if ctypes.CDLL(None).prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
        os._exit(1)
    if os.getppid() != parent_pid:
        os._exit(1)


class OpenboxMenu:
    """Derive session menu fonts from the immutable image configuration."""
    def __init__(self, template, destination):
        self.template, self.destination = template, destination
        self.notified = destination.with_name(destination.name + '.notified')
        self.pending, self.retry_at = None, 0

    def apply(self, scale):
        namespace = 'http://openbox.org/3.4/rc'
        ET.register_namespace('', namespace)
        tree = ET.parse(self.template)
        for font in tree.findall(f'.//{{{namespace}}}font'):
            if font.get('place') in ('MenuItem', 'MenuHeader'):
                size = font.find(f'{{{namespace}}}size')
                size.text = str(max(1, round(int(size.text) * scale / 100)))
        content = ET.tostring(tree.getroot(), encoding='UTF-8', xml_declaration=True)
        digest = hashlib.sha256(content).hexdigest()
        changed = not self.destination.exists() or self.destination.read_bytes() != content
        if not changed and read_json(self.notified) == digest:
            self.pending = None
            return
        if changed:
            self.destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.destination.with_suffix('.new')
            temporary.write_bytes(content)
            temporary.replace(self.destination)
        if self.pending != digest:
            self.pending, self.retry_at = digest, 0
        self.ensure()

    def ensure(self):
        if self.pending is None or time.monotonic() < self.retry_at:
            return
        # Before session startup there is no WM yet; it will read this file.
        # A slow/unavailable WM must not discard an authenticated density event.
        # Persist only successful notifications, so restart can retry unchanged XML.
        try:
            result = subprocess.run(['openbox', '--reconfigure'], stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=2, check=False)
            if result.returncode == 0:
                atomic_json(self.notified, self.pending)
                self.pending = None
                return
        except (OSError, subprocess.TimeoutExpired):
            pass
        self.retry_at = time.monotonic() + 2
        print('display-scale: menu notification pending retry', file=sys.stderr, flush=True)


class XSettings:
    def __init__(self, path, menu=None):
        self.path, self.child, self.retry_at, self.menu = path, None, 0, menu

    def apply(self, scale):
        if self.menu:
            self.menu.apply(scale)
        temporary = self.path.with_suffix('.new')
        temporary.write_text(settings(scale))
        temporary.replace(self.path)
        if self.child and self.child.poll() is None:
            self.child.send_signal(signal.SIGHUP)

    def ready(self):
        if self.menu:
            self.menu.ensure()
        if self.child and self.child.poll() is None:
            return selection_ready()
        if time.monotonic() >= self.retry_at:
            self.retry_at = time.monotonic() + 2
            try:
                # Keep child diagnostics free of client metadata and profile data.
                parent_pid = os.getpid()
                self.child = subprocess.Popen(['xsettingsd', '-c', str(self.path)],
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                               preexec_fn=lambda: child_guard(parent_pid))
            except OSError:
                self.child = None
            print('display-scale: starting XSettings service', file=sys.stderr, flush=True)
        return False

    def close(self):
        if self.child and self.child.poll() is None:
            self.child.terminate()
            try:
                self.child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait()


def worker_birth(pid):
    # Kernel credentials plus start ticks distinguish PID reuse after reconnects.
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rpartition(')')[2].split()
        return 0 if fields[0] in ('Z', 'X') else int(fields[19])
    except (OSError, ValueError, IndexError):
        return 0


def serve():
    os.umask(0o077)
    desktop_uid = os.getuid()
    xrdp_uid = pwd.getpwnam('xrdp').pw_uid
    # Lock survives stale socket files, but never permits two controller owners.
    with (RUNTIME / 'display-scale.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        daemon = XSettings(RUNTIME / 'xsettings.conf', OpenboxMenu(
            Path('/etc/xdg/openbox/rc.xml'), Path.home() / '.config/openbox/rc.xml'))
        policy = Policy(Path(os.environ['BROWSER_PROFILE_DIR']) / '.browser-desktop-scale.json',
                        RUNTIME / 'display-scale-state.json', daemon.apply)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        Path(SOCKET).unlink(missing_ok=True)
        server.bind(SOCKET)
        os.chmod(SOCKET, 0o660)
        server.settimeout(0.5)
        running = True

        def stop(signum, frame):
            nonlocal running
            running = False

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        try:
            while running:
                policy.expire_worker()
                ready = daemon.ready()
                try:
                    data, credentials, flags, address = server.recvmsg(MAX_EVENT + 1, socket.CMSG_SPACE(12))
                except socket.timeout:
                    continue
                if flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
                    continue
                for level, kind, value in credentials:
                    if level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS and len(value) == 12:
                        pid, uid, _ = struct.unpack('3i', value)
                        birth = worker_birth(pid) if uid == xrdp_uid else 0
                        if uid == xrdp_uid and not birth:
                            continue
                        try:
                            reply = dispatch(policy, data, uid, pid, desktop_uid, xrdp_uid, birth)
                        except OSError:
                            print('display-scale: state update failed', file=sys.stderr, flush=True)
                            reply = None
                        if reply is not None and address:
                            reply['daemon_ready'] = ready
                            try:
                                server.sendto(json.dumps(reply).encode(), socket.MSG_DONTWAIT, address)
                            except OSError:
                                pass
                        break
        finally:
            server.close()
            Path(SOCKET).unlink(missing_ok=True)
            daemon.close()


def request(op, value=None):
    data = dict(op=op)
    if value is not None:
        data['value'] = value
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
        client.settimeout(2)
        client.bind('\0browser-density-' + uuid.uuid4().hex)
        client.sendto(json.dumps(data).encode(), SOCKET)
        return json.loads(client.recv(MAX_EVENT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('serve', 'set', 'status'))
    parser.add_argument('value', nargs='?', choices=('auto', '100', '150', '200', '300'))
    args = parser.parse_args()
    if args.command == 'serve':
        serve()
        return 0
    if args.command == 'set' and args.value is None:
        parser.error('set requires a preset')
    try:
        result = request(args.command, args.value)
    except (OSError, ValueError, RecursionError):
        print(json.dumps({'daemon_ready': False, 'error': 'controller-unavailable'}))
        return 1
    print(json.dumps(result))
    return 0 if result['daemon_ready'] else 1


if __name__ == '__main__':
    sys.exit(main())
