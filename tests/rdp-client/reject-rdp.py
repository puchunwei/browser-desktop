"""Attempt a wrong synthetic login; the caller checks the server's AUTHFAIL."""
from pathlib import Path
import signal
import os
import subprocess
import sys
import time

host, port, user = sys.argv[1:4]
with Path('/evidence/rdp-wrong-auth.log').open('w') as log:
    client = subprocess.Popen(['xfreerdp3', '/args-from:stdin'], stdin=subprocess.PIPE,
        stdout=log, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    client.stdin.write('\n'.join([f'/v:{host}:{port}', f'/u:{user}', '/p:incorrect',
        '/cert:ignore', '/size:1280x720', '/log-level:INFO']) + '\n')
    client.stdin.close()
    time.sleep(8)
    if client.poll() is None:
        os.killpg(client.pid, signal.SIGTERM)
        try: client.wait(timeout=3)
        except subprocess.TimeoutExpired: os.killpg(client.pid, signal.SIGKILL); client.wait()
