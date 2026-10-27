"""Behavioral checks with disposable preferences; never open an owner profile."""
import ctypes
import importlib.util
import json
import os
import signal
import subprocess
import time
import sys
from pathlib import Path
import tempfile
import unittest

sys.dont_write_bytecode = True
SCRIPT = Path(__file__).resolve().parents[1] / 'image/display-scale.py'


class DensityTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), 'desktop density controller is not implemented')
        spec = importlib.util.spec_from_file_location('density', SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.applied = []
        self.policy = self.module.Policy(self.root / 'prefs', self.root / 'state', self.applied.append)

    def event(self, *, scale=200, device=100, hint='synthetic-client', kind='connect', pid=42,
              monitors=None, width=1600, height=1000, uid=200, birth=0):
        event = dict(op='event', kind=kind, desktop=scale, device=device,
                     hint=hint.encode().hex(), os=[6, 0], width=width, height=height,
                     monitors=monitors or [])
        return self.module.dispatch(self.policy, json.dumps(event).encode(), uid, pid, 1000, 200, birth)

    def test_native_phone_retina_preset_is_available(self):
        self.event(scale=100)
        result = self.module.dispatch(self.policy, b'{"op":"set","value":"300"}', 1000, 50, 1000, 200)
        self.assertIsNotNone(result)
        self.assertEqual(result['scale'], 300)

    def test_negotiated_scale_changes_settings(self):
        for scale in (100, 150, 200, 500):
            self.event(scale=scale)
            self.assertEqual(self.policy.status()['scale'], scale)
            self.assertEqual(self.policy.status()['source'], 'negotiated')

    def test_invalid_or_missing_scale_defaults_without_device_guess(self):
        for scale, device in ((0, 180), (99, 100), (501, 100), (200, 0), (200, 200)):
            self.event(scale=scale, device=device, pid=scale + device)
            self.assertEqual(self.policy.status()['scale'], 100)

    def test_small_retina_resize_preserves_density(self):
        self.event()
        self.event(kind='resize', width=640, height=900)
        self.assertEqual(self.policy.status()['scale'], 200)
        self.assertEqual(self.policy.status()['geometry'], [640, 900])

    def test_resize_does_not_clear_override(self):
        self.event()
        self.policy.set('150')
        self.event(kind='resize', width=1000, height=1600)
        self.assertEqual(self.policy.status()['scale'], 150)

    def test_reused_worker_pid_is_a_new_unknown_connection(self):
        self.event(hint='', birth=100)
        self.policy.set('150')
        self.event(hint='', scale=100, birth=200)
        self.assertEqual(self.policy.status()['scale'], 100)

    def test_unknown_client_never_inherits_previous_override(self):
        self.event()
        self.policy.set('200')
        self.event(hint='', scale=0, device=0, pid=43)
        self.assertEqual(self.policy.status()['scale'], 100)
        self.policy.set('150')
        self.event(hint='', scale=0, device=0, pid=44)
        self.assertEqual(self.policy.status()['scale'], 100)

    def test_per_client_override_and_auto_survive_reconnect(self):
        self.event(hint='one')
        self.policy.set('150')
        self.event(hint='two', scale=100, pid=43)
        self.assertEqual(self.policy.status()['scale'], 100)
        self.event(hint='one', pid=44)
        self.assertEqual(self.policy.status()['scale'], 150)
        self.policy.set('auto')
        self.assertEqual(self.policy.status()['scale'], 200)
        self.event(hint='one', pid=45)
        self.assertEqual(self.policy.status()['scale'], 200)

    def test_monitor_metadata_preferred_and_mixed_density_explicit(self):
        self.event(scale=100, monitors=[[200, 100], [200, 100]])
        self.assertEqual(self.policy.status()['scale'], 200)
        self.event(monitors=[[100, 100], [200, 100]])
        self.assertEqual(self.policy.status()['scale'], 100)
        self.assertEqual(self.policy.status()['source'], 'mixed-monitors')
        self.policy.set('150')
        self.assertEqual(self.policy.status()['scale'], 150)

    def test_incomplete_monitor_metadata_not_guessed(self):
        self.event(monitors=[[200, 100], [0, 0]])
        self.assertEqual(self.policy.status()['scale'], 100)
        self.assertEqual(self.policy.status()['source'], 'invalid-monitors')

    def test_corrupt_preferences_fall_back(self):
        for data in ('{broken', '[]', '{"abc":200}', '{"' + 'a' * 64 + '":true}'):
            (self.root / 'prefs').write_text(data)
            self.policy = self.module.Policy(self.root / 'prefs', self.root / 'state', self.applied.append)
            self.event(scale=100)
            self.assertEqual(self.policy.status()['scale'], 100)

    def test_restart_recovers_connection_override(self):
        self.event(hint='')
        self.policy.set('150')
        self.policy = self.module.Policy(self.root / 'prefs', self.root / 'state', self.applied.append)
        self.assertEqual(self.policy.status()['scale'], 150)
        self.event(kind='resize', hint='', width=1000)
        self.assertEqual(self.policy.status()['scale'], 150)

    def test_duplicate_event_does_not_reload_xsettings(self):
        self.event()
        count = len(self.applied)
        self.event()
        self.event(kind='resize', width=640)
        self.assertEqual(len(self.applied), count)

    def test_stale_worker_resize_does_not_change_current_client(self):
        self.event(pid=42)
        self.event(pid=43, scale=100)
        self.event(pid=42, kind='resize')
        self.assertEqual(self.policy.status()['scale'], 100)

    def test_malformed_oversized_and_unauthorized_events_are_rejected(self):
        self.event()
        old = self.policy.status()
        bad = (b'{', b'[]', b'x' * 4097, b'{"op":"set","value":"999"}',
               b'{"op":"event","kind":"connect"}', b'[' * 1500 + b']' * 1500)
        for raw in bad:
            self.assertIsNone(self.module.dispatch(self.policy, raw, 200, 42, 1000, 200))
        self.assertIsNone(self.event(uid=1234, scale=100))
        self.assertIsNone(self.module.dispatch(self.policy, b'{"op":"set","value":"100"}', 200, 42, 1000, 200))
        self.assertEqual(self.policy.status(), old)

    def test_raw_client_hint_never_persisted_or_in_status(self):
        self.event(hint='sensitive-name')
        self.policy.set('150')
        for path in (self.root / 'prefs', self.root / 'state'):
            self.assertNotIn('sensitive-name', path.read_text())
            self.assertNotIn('sensitive-name'.encode().hex(), path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(set(self.policy.status()), {'scale', 'source', 'geometry'})

    def test_controller_death_does_not_leave_an_orphan_xsettings_owner(self):
        # Adopt/reap only this test's grandchildren; no host service is touched.
        libc = ctypes.CDLL(None)
        previous = ctypes.c_int()
        self.assertEqual(libc.prctl(37, ctypes.byref(previous), 0, 0, 0), 0)
        self.assertEqual(libc.prctl(36, 1, 0, 0, 0), 0)
        fake = self.root / 'xsettingsd'
        fake.write_text('#!/bin/sh\nexec sleep 60\n')
        fake.chmod(0o700)
        code = ("import importlib.util, pathlib, time; "
                f"s=importlib.util.spec_from_file_location('density', {str(SCRIPT)!r}); "
                "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                f"d=m.XSettings(pathlib.Path({str(self.root / 'settings')!r})); "
                "d.ready(); print(d.child.pid, flush=True); time.sleep(60)")
        env = dict(os.environ, PATH=str(self.root) + ':' + os.environ['PATH'], PYTHONDONTWRITEBYTECODE='1')
        worker = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, env=env)
        child = None
        reaped = False
        try:
            child = int(worker.stdout.readline())
            worker.kill()
            worker.wait(timeout=2)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                pid, status = os.waitpid(child, os.WNOHANG)
                if pid:
                    reaped = True
                    break
                time.sleep(0.02)
            self.assertTrue(reaped, 'xsettingsd survived controller death')
            self.assertTrue(os.WIFSIGNALED(status))
            self.assertEqual(os.WTERMSIG(status), signal.SIGTERM)
        finally:
            if worker.poll() is None:
                worker.kill()
                worker.wait()
            worker.stdout.close()
            if child and not reaped:
                os.kill(child, signal.SIGKILL)
                os.waitpid(child, 0)
            libc.prctl(36, previous.value, 0, 0, 0)

    def test_fractional_settings_do_not_double_integer_scaling(self):
        for scale, dpi, factor, unscaled in ((100, 98304, 1, 98304),
                                             (150, 147456, 1, 147456),
                                             (200, 196608, 2, 98304),
                                             (300, 294912, 3, 98304)):
            settings = self.module.settings(scale)
            self.assertIn(f'Xft/DPI {dpi}\n', settings)
            self.assertIn(f'Gdk/WindowScalingFactor {factor}\n', settings)
            self.assertIn(f'Gdk/UnscaledDPI {unscaled}\n', settings)


if __name__ == '__main__':
    unittest.main()
