#!/usr/bin/env python3
"""restart-bot.py — restart the Discord bot (OC-042).

The bot runs under bin\\run-bot.cmd (a restart loop) started at boot by the Task Scheduler
task "OpenclawDiscordBot" (bin\\install-bot-autostart.ps1). Restarting = ending the
discord-bot.py process; run-bot.cmd starts a fresh one ~15s later.

If the task is not running (e.g. not installed yet), it is started with `schtasks /run`.
Replaces the old NSSM `sc stop/start` flow (service broken, OC-027).
"""
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

LOGDIR = Path(os.getenv('LOCALAPPDATA', '')) / 'openclaw'
LOG_FILE = LOGDIR / 'bot.log'
TASK = 'OpenclawDiscordBot'


def bot_pids() -> list:
    """PIDs of python processes running discord-bot.py."""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -like '*discord-bot.py*' } | "
          "Select-Object -ExpandProperty ProcessId | ConvertTo-Json")
    r = subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True, text=True)
    out = r.stdout.strip()
    if not out:
        return []
    data = json.loads(out)
    return data if isinstance(data, list) else [data]


def task_running() -> bool:
    r = subprocess.run(['schtasks', '/query', '/tn', TASK, '/fo', 'csv', '/nh'],
                       capture_output=True, text=True)
    return r.returncode == 0 and '"Running"' in r.stdout


def log_size() -> int:
    try:
        return LOG_FILE.stat().st_size
    except OSError:
        return 0


def ready_since(offset: int) -> bool:
    """True if bot.log has a 'ready user=' line written after byte offset."""
    try:
        with LOG_FILE.open('rb') as fh:
            fh.seek(offset if offset <= log_size() else 0)
            return b'ready user=' in fh.read()
    except OSError:
        return False


def main():
    offset = log_size()
    pids = bot_pids()
    running = task_running()
    print(f'task {TASK}: {"running" if running else "not running"}; bot pids: {pids or "none"}')

    for pid in pids:
        subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True)
        print(f'  stopped bot pid {pid}')

    if not pids and not running:  # nothing to restart in place: start the task
        r = subprocess.run(['schtasks', '/run', '/tn', TASK], capture_output=True, text=True)
        if r.returncode != 0:
            print(f'schtasks /run failed: {r.stdout.strip()} {r.stderr.strip()}')
            print('Install the boot task first: bin\\install-bot-autostart.ps1 (as administrator),')
            print('or run the bot manually: python D:\\MyData\\Software\\openclaw-config\\bin\\discord-bot.py')
            sys.exit(1)
        print(f'  started task {TASK}')

    print('Waiting for bot to connect to Discord...')
    for i in range(45):
        time.sleep(1)
        if ready_since(offset):
            print(f'OK discord-bot ready (after {i + 1}s)')
            sys.exit(0)
    print('Bot did not log "ready" within 45s. Last bot.log lines:')
    try:
        for line in LOG_FILE.read_text(encoding='utf-8', errors='replace').splitlines()[-5:]:
            print(f'  {line}')
    except OSError:
        pass
    sys.exit(1)


if __name__ == '__main__':
    main()
