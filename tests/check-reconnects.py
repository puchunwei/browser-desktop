"""Require test reconnects to reuse the existing session, allowing other viewers."""
import argparse
from pathlib import Path
import re

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('log', type=Path)
parser.add_argument('display')
parser.add_argument('session_pid', type=int)
parser.add_argument('minimum', type=int)
parser.add_argument('--user', default='browser')
args = parser.parse_args()
expected_display = int(args.display.removeprefix('DISPLAY=').removeprefix(':').split('.')[0])
if args.minimum < 1 or args.session_pid < 1:
    parser.error('minimum and session PID must be positive')

rows = [line for line in args.log.read_text().splitlines()
        if f'reconnected session: username {args.user},' in line]
if len(rows) < args.minimum:
    raise SystemExit(f'FAIL: only {len(rows)} reconnects; need at least {args.minimum}')
for row in rows:
    match = re.search(r'reconnected session: username ' + re.escape(args.user) + r', display :(\d+)(?:\.0)?, session_pid (\d+),', row)
    if not match:
        raise SystemExit('FAIL: unrecognized session reconnect record')
    if (int(match[1]), int(match[2])) != (expected_display, args.session_pid):
        raise SystemExit('FAIL: a reconnect used a different display or session process')
print(f'OK: {len(rows)} reconnects reused display :{expected_display}, '
      f'session {args.session_pid}; minimum {args.minimum}')
