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

# The gateways run on the Raspberry Pi 5 as systemd services (moved off this PC 2026-10-24).
PI_HOST = os.getenv('GATEWAY_PI_HOST', 'pi5.local')   # HTTP host for /ping
PI_SSH = os.getenv('GATEWAY_PI_SSH', 'pi5')           # ssh alias from ~/.ssh/config
PI_LOG_DIR = '~/gemini_gateway/logs'
GATEWAYS = {
    'gemini': {'service': 'gemini-gateway', 'port': 18790},
    'chatgpt': {'service': 'chatgpt-gateway', 'port': 18791},
}
ALIASES = {'gemini': 'gemini', 'chatgpt': 'chatgpt', 'gpt': 'chatgpt', 'openai': 'chatgpt'}
START_WAIT_S = 90   # Chromium on the Pi takes ~30-60 s to log in and warm up


def resolve(name: str) -> str | None:
    return ALIASES.get(name.lower())


def is_up(key: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(f'http://{PI_HOST}:{GATEWAYS[key]["port"]}/ping', timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def status() -> dict[str, bool]:
    return {k: is_up(k) for k in GATEWAYS}


def start(key: str) -> dict:
    """Restart a gateway's systemd service on the Pi unless it already answers /ping.
    Returns {'state', 'detail'} where state is 'already_up' | 'started' | 'failed'."""
    g = GATEWAYS[key]
    if is_up(key):
        return {'state': 'already_up', 'port': g['port']}
    try:
        proc = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=10', '-o', 'BatchMode=yes', PI_SSH,
             f'sudo systemctl restart {g["service"]}'],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'state': 'failed', 'detail': f'ssh {PI_SSH} failed: {exc}', 'port': g['port']}
    if proc.returncode != 0:
        return {'state': 'failed', 'detail': f'systemctl restart exited {proc.returncode}: '
                f'{(proc.stderr or proc.stdout).strip()[:200]}', 'port': g['port']}
    deadline = time.monotonic() + START_WAIT_S
    while time.monotonic() < deadline:
        if is_up(key):
            return {'state': 'started', 'port': g['port']}
        time.sleep(2)
    return {'state': 'failed', 'detail': f'no /ping response after {START_WAIT_S}s; see '
            f'{PI_LOG_DIR}/{key}_gateway.log on {PI_SSH}', 'port': g['port']}
