#!/usr/bin/env python3
"""restart-bot.py — restart the discord-bot service without admin elevation.

Uses sc stop + sc start, which works because manage-service.ps1 grant-user
has already granted the current user start/stop rights on discord-bot.

NSSM's AppStopMethodConsole=3000 + AppKillProcessTree=1 ensure the Python
process is killed within ~6s even if it doesn't respond to Ctrl+C.
"""
import io
import os
import subprocess
import sys
import time
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

LOGDIR = Path(os.getenv('LOCALAPPDATA', '')) / 'openclaw'
LOG_FILE = LOGDIR / 'bot.log'
SERVICE = 'discord-bot'


def sc(*args):
    return subprocess.run(['sc.exe'] + list(args), capture_output=True, text=True)


def tail_log(n=5):
    try:
        lines = LOG_FILE.read_text(encoding='utf-8', errors='replace').splitlines()
        return lines[-n:]
    except Exception:
        return []


def main():
    print(f'Stopping {SERVICE}...')
    r = sc('stop', SERVICE)
    if r.returncode not in (0, 1062):  # 1062 = not started
        print(f'sc stop failed: {r.stdout.strip()} {r.stderr.strip()}')
        sys.exit(1)

    # Wait for service to reach STOPPED state
    for i in range(15):
        time.sleep(1)
        q = sc('query', SERVICE)
        if 'STOPPED' in q.stdout:
            print(f'  stopped after {i + 1}s')
            break
    else:
        print('Service did not stop within 15s.')
        sys.exit(1)

    print(f'Starting {SERVICE}...')
    r = sc('start', SERVICE)
    if r.returncode != 0:
        print(f'sc start failed: {r.stdout.strip()} {r.stderr.strip()}')
        sys.exit(1)

    # Wait for bot to log "ready user="
    print('Waiting for bot to connect to Discord...')
    for i in range(20):
        time.sleep(1)
        recent = tail_log(5)
        if any('ready user=' in l for l in recent):
            print(f'OK discord-bot ready (after {i + 1}s)')
            sys.exit(0)

    print('Bot did not log "ready" within 20s.')
    for line in tail_log(5):
        print(f'  {line}')
    sys.exit(1)


if __name__ == '__main__':
    main()
