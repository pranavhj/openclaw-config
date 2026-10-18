#!/usr/bin/env python3
"""
rc_gateways.py — start/inspect the Gemini and ChatGPT gateways from the Discord `rc gateway`
command. The bot calls these in a thread; nothing here talks to Discord.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

SERVICE_DIR = Path(r'C:\Users\prana\AndroidStudioProjects\gemini_gateway\service')
LOGDIR = Path(os.getenv('LOCALAPPDATA') or tempfile.gettempdir()) / 'openclaw'
GATEWAYS = {
    'gemini': {'script': 'gemini_gateway.py', 'port': 18790},
    'chatgpt': {'script': 'chatgpt_gateway.py', 'port': 18791},
}
ALIASES = {'gemini': 'gemini', 'chatgpt': 'chatgpt', 'gpt': 'chatgpt', 'openai': 'chatgpt'}
START_WAIT_S = 45


def resolve(name: str) -> str | None:
    return ALIASES.get(name.lower())


def is_up(key: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f'http://localhost:{GATEWAYS[key]["port"]}/ping', timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def status() -> dict[str, bool]:
    return {k: is_up(k) for k in GATEWAYS}


def start(key: str) -> dict:
    """Start a gateway detached unless it already answers /ping. Returns {'state', 'detail'}
    where state is 'already_up' | 'started' | 'failed'."""
    g = GATEWAYS[key]
    if is_up(key):
        return {'state': 'already_up', 'port': g['port']}
    script = SERVICE_DIR / g['script']
    if not script.exists():
        return {'state': 'failed', 'detail': f'{script} not found', 'port': g['port']}
    LOGDIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGDIR / f'{key}-gateway.log'
    with open(log_path, 'ab') as log:
        proc = subprocess.Popen(
            [sys.executable, str(script)], cwd=str(SERVICE_DIR), stdin=subprocess.DEVNULL,
            stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            | getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    deadline = time.monotonic() + START_WAIT_S
    while time.monotonic() < deadline:
        if is_up(key):
            return {'state': 'started', 'pid': proc.pid, 'port': g['port']}
        if proc.poll() is not None:
            return {'state': 'failed', 'detail': f'exited with code {proc.returncode}; see {log_path}',
                    'port': g['port']}
        time.sleep(1)
    return {'state': 'failed', 'detail': f'no /ping response after {START_WAIT_S}s; see {log_path}',
            'port': g['port']}
