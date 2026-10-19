"""Replay the extra-client regression and reject real session replacement."""
import pathlib
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
LINE = ('[INFO ] ++ reconnected session: username browser, '
        'display :10.0, session_pid 1151, ip 127.0.0.1\n')


class Reconnects(unittest.TestCase):
    def check_log(self, text, success):
        with tempfile.TemporaryDirectory() as directory:
            log = pathlib.Path(directory) / 'sesman.log'
            log.write_text(text)
            result = subprocess.run(['python3', str(HERE / 'check-reconnects.py'),
                                     str(log), 'DISPLAY=:10', '1151', '3'],
                                    capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stderr)

    def test_three_test_connections(self):
        self.check_log(LINE * 3, True)

    def test_extra_owner_connection_reuses_the_session(self):
        self.check_log(LINE * 4, True)

    def test_missing_test_connection(self):
        self.check_log(LINE * 2, False)

    def test_extra_connection_to_another_display(self):
        self.check_log(LINE * 3 + LINE.replace(':10.0', ':11.0'), False)

    def test_replacement_session_on_same_display(self):
        self.check_log(LINE * 3 + LINE.replace('1151', '1152'), False)

    def test_unrecognized_reconnect_cannot_be_ignored(self):
        self.check_log(LINE * 3 + LINE.replace('1151', 'unknown'), False)


if __name__ == '__main__':
    unittest.main()
