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
from unittest.mock import patch
import xml.etree.ElementTree as ET

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
        # Synthetic worker generations model only the external /proc boundary.
        # Recovery regressions below use actual subprocess lifetimes instead.
        self.workers = {}
        self.worker_lookup = lambda pid: self.workers.get(pid, self.module.worker_birth(pid))
        self.policy = self.module.Policy(self.root / 'prefs', self.root / 'state', self.applied.append, self.worker_lookup)

    def event(self, *, scale=200, device=100, hint='synthetic-client', kind='connect', pid=42,
              monitors=None, width=1600, height=1000, uid=200, birth=1, real=False):
        if not real:
            self.workers[pid] = birth
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
            self.policy = self.module.Policy(self.root / 'prefs', self.root / 'state', self.applied.append, self.worker_lookup)
            self.event(scale=100)
            self.assertEqual(self.policy.status()['scale'], 100)

    def test_restart_recovers_connection_override(self):
        self.event(hint='')
        self.policy.set('150')
        self.policy = self.module.Policy(self.root / 'prefs', self.root / 'state', self.applied.append, self.worker_lookup)
        self.assertEqual(self.policy.status()['scale'], 150)
        self.event(kind='resize', hint='', width=1000)
        self.assertEqual(self.policy.status()['scale'], 150)

    def test_duplicate_event_does_not_reload_xsettings(self):
        self.event()
        count = len(self.applied)
        self.event()
        self.event(kind='resize', width=640)
        self.assertEqual(len(self.applied), count)

    def test_menu_scale_restore_and_recovery_use_immutable_sizes(self):
        template = self.root / 'template.xml'
        destination = self.root / 'config/openbox/rc.xml'
        template.write_text('''<openbox_config xmlns="http://openbox.org/3.4/rc"><theme>
        <font place="MenuItem"><size>9</size></font>
        <font place="MenuHeader"><size>9</size></font>
        <font place="ActiveWindow"><size>8</size></font></theme></openbox_config>''')
        menu = self.module.OpenboxMenu(template, destination)
        with patch.object(self.module.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as reconfigure:
            for scale, expected in ((100, 9), (150, 14), (200, 18), (300, 27), (100, 9)):
                menu.apply(scale)
                sizes = [int(e.text) for e in ET.parse(destination).iter()
                         if e.tag.endswith('}size')]
                self.assertEqual(sizes, [expected, expected, 8])
            count = reconfigure.call_count
            menu.apply(100)
            self.module.OpenboxMenu(template, destination).apply(100)
            self.assertEqual(reconfigure.call_count, count)
            self.assertEqual(reconfigure.call_args.args[0], ['openbox', '--reconfigure'])
        self.assertIn('<size>9</size>', template.read_text())

    def test_menu_timeout_keeps_authenticated_state_and_retries_without_new_event(self):
        template, destination = self.root / 'template.xml', self.root / 'rc.xml'
        template.write_text('<openbox_config xmlns="http://openbox.org/3.4/rc"><theme>'
                            '<font place="MenuItem"><size>9</size></font></theme></openbox_config>')
        notified = self.root / 'wm-applied.xml'
        outcomes = [0, subprocess.TimeoutExpired(['openbox', '--reconfigure'], 2), 0]
        def notify(*args, **kwargs):
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            notified.write_bytes(destination.read_bytes())
            return subprocess.CompletedProcess(args[0], outcome)
        menu = self.module.OpenboxMenu(template, destination)
        daemon = self.module.XSettings(self.root / 'xsettings.conf', menu)
        with patch.object(self.module.subprocess, 'run', side_effect=notify), \
                patch.object(self.module.time, 'monotonic', return_value=100) as clock:
            self.policy = self.module.Policy(self.root / 'prefs', self.root / 'state', daemon.apply, self.worker_lookup)
            self.event(scale=200)
            self.assertEqual(json.loads((self.root / 'state').read_text())['pid'], 42)
            self.assertEqual(json.loads((self.root / 'state').read_text())['desktop'], 200)
            self.assertIn('Xft/DPI 196608', daemon.path.read_text())
            self.assertIn('<size>9</size>', notified.read_text())
            # The existing controller readiness loop retries notification without
            # needing another RDP event or rewriting the negotiated density.
            with patch.object(self.module, 'selection_ready', return_value=True), \
                    patch.object(self.module.subprocess, 'Popen') as child:
                child.return_value.poll.return_value = None
                daemon.ready()
                self.assertIn('<size>9</size>', notified.read_text())
                clock.return_value = 103
                daemon.ready()
            self.assertIn('<size>18</size>', notified.read_text())
            self.assertEqual(self.policy.status()['scale'], 200)
            self.assertEqual(outcomes, [])

    def test_menu_nonzero_notification_recovers_after_controller_restart(self):
        template, destination = self.root / 'template.xml', self.root / 'rc.xml'
        template.write_text('<openbox_config xmlns="http://openbox.org/3.4/rc"><theme>'
                            '<font place="MenuItem"><size>9</size></font></theme></openbox_config>')
        notified = self.root / 'wm-applied.xml'
        outcomes = [0, 1, 0]
        def notify(*args, **kwargs):
            outcome = outcomes.pop(0)
            if outcome == 0:
                notified.write_bytes(destination.read_bytes())
            return subprocess.CompletedProcess(args[0], outcome)
        with patch.object(self.module.subprocess, 'run', side_effect=notify):
            menu = self.module.OpenboxMenu(template, destination)
            menu.apply(100)
            menu.apply(300)
            self.assertIn('<size>27</size>', destination.read_text())
            self.assertIn('<size>9</size>', notified.read_text())
            recovered = self.module.OpenboxMenu(template, destination)
            recovered.apply(300)
            self.assertIn('<size>27</size>', notified.read_text())
            recovered.apply(300)
            self.assertEqual(outcomes, [])

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

    def live_worker(self):
        worker = subprocess.Popen(['sleep', '60'])
        self.addCleanup(lambda: worker.wait() if worker.poll() is not None else (worker.kill(), worker.wait()))
        return worker, self.module.worker_birth(worker.pid)

    def test_restart_drops_dead_workers_override_before_any_new_event(self):
        worker, birth = self.live_worker()
        self.event(pid=worker.pid, birth=birth, hint='client-A', real=True)
        self.policy.set('300')
        worker.terminate()
        worker.wait()
        self.policy = self.module.Policy(self.root / 'prefs', self.root / 'state', self.applied.append, self.worker_lookup)
        self.assertEqual(self.policy.status(), dict(scale=100, source='default', geometry=[0, 0]))

    def test_missed_connect_recovers_unknown_worker_from_resize_without_old_preference(self):
        worker, birth = self.live_worker()
        self.event(pid=worker.pid, birth=birth, hint='client-A', real=True)
        self.policy.set('300')
        saved_preferences = (self.root / 'prefs').read_text()
        worker.terminate()
        worker.wait()
        # B connects while the controller is absent, so its connect event is lost.
        self.policy = self.module.Policy(self.root / 'prefs', self.root / 'state', self.applied.append, self.worker_lookup)
        self.event(pid=os.getpid(), birth=self.module.worker_birth(os.getpid()), kind='resize', real=True,
                   hint='', scale=0, device=0, width=640, height=900)
        self.assertEqual(self.policy.status(), dict(scale=100, source='default', geometry=[640, 900]))
        self.policy.set('150')
        self.assertEqual((self.root / 'prefs').read_text(), saved_preferences)

    def test_manual_change_after_disconnect_does_not_overwrite_old_client_preference(self):
        worker, birth = self.live_worker()
        self.event(pid=worker.pid, birth=birth, hint='client-A', real=True)
        self.policy.set('300')
        saved_preferences = (self.root / 'prefs').read_text()
        worker.terminate()
        worker.wait()
        self.policy.set('150')
        self.assertEqual((self.root / 'prefs').read_text(), saved_preferences)
        self.assertEqual(self.policy.status()['scale'], 150)

    def test_exited_unreaped_worker_is_not_a_live_connection(self):
        worker, birth = self.live_worker()
        self.assertGreater(birth, 0)
        self.event(pid=worker.pid, birth=birth, hint='client-A', real=True)
        self.policy.set('300')
        worker.terminate()
        os.waitid(os.P_PID, worker.pid, os.WEXITED | os.WNOWAIT)
        # Its /proc entry remains until wait(), but the connection is over.
        self.policy = self.module.Policy(self.root / 'prefs', self.root / 'state', self.applied.append, self.worker_lookup)
        self.assertEqual(self.policy.status()['scale'], 100)
        worker.wait()

    def test_restart_rejects_reused_pid_generation(self):
        self.event(pid=os.getpid(), birth=self.module.worker_birth(os.getpid()), hint='', real=True)
        self.policy.set('150')
        state = json.loads((self.root / 'state').read_text())
        state['birth'] -= 1
        (self.root / 'state').write_text(json.dumps(state))
        self.policy = self.module.Policy(self.root / 'prefs', self.root / 'state', self.applied.append, self.worker_lookup)
        self.assertEqual(self.policy.status()['scale'], 100)

    def test_preexec_guard_cannot_return_after_parent_mismatch_with_inherited_handler(self):
        child = os.fork()
        if child == 0:
            signal.signal(signal.SIGTERM, lambda signum, frame: None)
            self.module.child_guard(os.getppid() + 1)
            os._exit(0)
        _, status = os.waitpid(child, 0)
        self.assertNotEqual(os.waitstatus_to_exitcode(status), 0, 'guard returned after parent mismatch')

    def test_preexec_guard_resets_the_inherited_service_sigterm_handler(self):
        child = os.fork()
        if child == 0:
            signal.signal(signal.SIGTERM, lambda signum, frame: None)
            self.module.child_guard(os.getppid())
            os.kill(os.getpid(), signal.SIGTERM)
            os._exit(0)
        _, status = os.waitpid(child, 0)
        self.assertTrue(os.WIFSIGNALED(status), 'inherited handler swallowed SIGTERM')
        self.assertEqual(os.WTERMSIG(status), signal.SIGTERM)

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
                "import signal; signal.signal(signal.SIGTERM, lambda signum, frame: None); "
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
