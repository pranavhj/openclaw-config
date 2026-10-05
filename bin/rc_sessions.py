#!/usr/bin/env python3
"""
rc_sessions.py — start Claude Code Remote Control sessions headlessly (OC-041).

Building block for the Discord `rc` command: trust a folder, launch
`claude --bg --remote-control`, wait until the Remote Control bridge is up,
and return the claude.ai link.

Importable module + standalone CLI:
    python rc_sessions.py start <project_path> [--name N] [--resume SESSION_ID]
    python rc_sessions.py trust <project_path>

Verified facts (claude 2.1.289, 2026-10-05):
  - `claude --bg --remote-control -n NAME` runs with no terminal; prints
    "backgrounded · <jobId>"; the session's ~/.claude/sessions/<pid>.json gets
    a `bridgeSessionId` once Remote Control is connected.
  - Untrusted folders fail with "Workspace not trusted"; setting
    ~/.claude.json projects["C:/fwd/slash/path"].hasTrustDialogAccepted=true fixes it.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

LOGDIR = Path(os.getenv('LOCALAPPDATA') or tempfile.gettempdir()) / 'openclaw'
CLAUDE_CONFIG = Path.home() / '.claude.json'
SESSIONS_DIR = Path.home() / '.claude' / 'sessions'
# ASSUMPTION (unverified): Remote Control sessions open at claude.ai/code/<bridgeSessionId>
RC_URL_PREFIX = 'https://claude.ai/code/'
DEFAULT_PERMISSION_MODE = 'bypassPermissions'

log = logging.getLogger('rc_sessions')
if not log.handlers:
    LOGDIR.mkdir(parents=True, exist_ok=True)
    _h = logging.FileHandler(LOGDIR / 'rc-sessions.log', encoding='utf-8')
    _h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    log.addHandler(_h)
    log.setLevel(logging.DEBUG)


class RCError(RuntimeError):
    """A Remote Control session could not be started or did not come up."""


def config_key(project_path: str | Path) -> str:
    """Key used in ~/.claude.json `projects` (forward slashes, e.g. C:/Users/x/proj)."""
    return str(Path(project_path).resolve()).replace('\\', '/')


def _read_config(config_path: Path) -> dict:
    return json.loads(config_path.read_text(encoding='utf-8'))


def is_trusted(project_path: str | Path, config_path: Path = CLAUDE_CONFIG) -> bool:
    try:
        cfg = _read_config(config_path)
    except (OSError, json.JSONDecodeError) as e:
        log.warning('is_trusted: cannot read %s: %s', config_path, e)
        return False
    entry = cfg.get('projects', {}).get(config_key(project_path), {})
    return bool(entry.get('hasTrustDialogAccepted'))


def ensure_trusted(project_path: str | Path, config_path: Path = CLAUDE_CONFIG,
                   attempts: int = 3) -> bool:
    """Mark folder trusted. Re-reads after writing because running claude
    processes also rewrite ~/.claude.json and may clobber the flag."""
    key = config_key(project_path)
    if is_trusted(project_path, config_path):
        log.debug('ensure_trusted: already trusted %s', key)
        return True
    for attempt in range(1, attempts + 1):
        try:
            cfg = _read_config(config_path)
            cfg.setdefault('projects', {}).setdefault(key, {})['hasTrustDialogAccepted'] = True
            tmp = config_path.with_name(config_path.name + '.rc-tmp')
            tmp.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
            os.replace(tmp, config_path)
        except (OSError, json.JSONDecodeError) as e:
            log.warning('ensure_trusted: attempt %d write failed for %s: %s', attempt, key, e)
            time.sleep(0.5)
            continue
        time.sleep(0.3)
        if is_trusted(project_path, config_path):
            log.info('ensure_trusted: trusted %s (attempt %d)', key, attempt)
            return True
        log.warning('ensure_trusted: flag lost after write for %s (attempt %d)', key, attempt)
    log.error('ensure_trusted: gave up on %s after %d attempts', key, attempts)
    return False


def claude_exe() -> str:
    exe = shutil.which('claude')
    if not exe:
        raise RCError('claude CLI not found on PATH')
    return exe


def build_start_cmd(name: str, resume_id: str | None = None,
                    permission_mode: str = DEFAULT_PERMISSION_MODE) -> list[str]:
    cmd = [claude_exe(), '--bg']
    if resume_id:
        cmd += ['--resume', resume_id]
    cmd += ['--remote-control', '-n', name, '--permission-mode', permission_mode]
    return cmd


_JOB_RE = re.compile(r'backgrounded\s*·\s*([0-9a-f]{8})')


def parse_job_id(output: str) -> str | None:
    m = _JOB_RE.search(output)
    return m.group(1) if m else None


def find_session(job_id: str, sessions_dir: Path = SESSIONS_DIR) -> dict | None:
    """Return the ~/.claude/sessions/*.json record for a background job id."""
    if not sessions_dir.exists():
        return None
    for f in sessions_dir.glob('*.json'):
        try:
            rec = json.loads(f.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue  # file being rewritten by its owner; next poll will see it
        if rec.get('jobId') == job_id:
            return rec
    return None


def wait_for_bridge(job_id: str, timeout_s: float = 30, poll_s: float = 1,
                    sessions_dir: Path = SESSIONS_DIR) -> dict | None:
    """Poll until the session record has a bridgeSessionId. Returns the record or None."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        rec = find_session(job_id, sessions_dir)
        if rec and rec.get('bridgeSessionId'):
            return rec
        time.sleep(poll_s)
    return None


def logs_tail(job_id: str, lines: int = 15) -> str:
    """Last lines of `claude logs <id>`, ANSI stripped — for failure reports."""
    try:
        r = subprocess.run([claude_exe(), 'logs', job_id], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=30,
                           stdin=subprocess.DEVNULL)
        out = re.sub(r'\x1b\[[0-9;?]*[A-Za-z]', '', r.stdout + r.stderr)
        kept = [ln.rstrip() for ln in out.splitlines() if ln.strip()]
        return '\n'.join(kept[-lines:])
    except (subprocess.SubprocessError, OSError, RCError) as e:
        return f'(could not read logs: {e})'


def start_rc(project_path: str | Path, name: str | None = None, resume_id: str | None = None,
             permission_mode: str = DEFAULT_PERMISSION_MODE, timeout_s: float = 30) -> dict:
    """Trust the folder, start a background Remote Control session, wait for the bridge.

    Returns {job_id, session_id, bridge_session_id, url, name, cwd}. Raises RCError.
    """
    project = Path(project_path)
    if not project.is_dir():
        raise RCError(f'project folder does not exist: {project}')
    name = name or project.name
    log.info('start_rc: project=%s name=%s resume=%s mode=%s', project, name, resume_id, permission_mode)

    if not ensure_trusted(project):
        raise RCError(f'could not mark {project} as trusted in {CLAUDE_CONFIG}')

    cmd = build_start_cmd(name, resume_id, permission_mode)
    log.debug('start_rc: cmd=%s cwd=%s', cmd, project)
    try:
        r = subprocess.run(cmd, cwd=str(project), capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=60,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        raise RCError(f'claude --bg did not return within 60s') from e
    out = (r.stdout or '') + (r.stderr or '')
    log.debug('start_rc: rc=%s output=%r', r.returncode, out[:500])
    if 'not trusted' in out.lower():
        raise RCError(f'workspace still not trusted: {out.strip()[:200]}')
    job_id = parse_job_id(out)
    if not job_id:
        raise RCError(f'could not parse job id (exit {r.returncode}): {out.strip()[:300]}')

    rec = wait_for_bridge(job_id, timeout_s)
    if not rec:
        tail = logs_tail(job_id)
        log.error('start_rc: no bridge for job=%s after %ss; logs:\n%s', job_id, timeout_s, tail)
        raise RCError(f'session {job_id} started but Remote Control did not connect '
                      f'within {timeout_s}s.\n{tail}')
    result = {
        'job_id': job_id,
        'session_id': rec.get('sessionId'),
        'bridge_session_id': rec['bridgeSessionId'],
        'url': RC_URL_PREFIX + rec['bridgeSessionId'],
        'name': rec.get('name', name),
        'cwd': rec.get('cwd', str(project)),
    }
    log.info('start_rc: ready job=%s bridge=%s', job_id, result['bridge_session_id'])
    return result


if __name__ == '__main__':
    import argparse
    import sys

    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('start')
    s.add_argument('project_path')
    s.add_argument('--name')
    s.add_argument('--resume')
    s.add_argument('--permission-mode', default=DEFAULT_PERMISSION_MODE)
    t = sub.add_parser('trust')
    t.add_argument('project_path')
    a = ap.parse_args()
    try:
        if a.cmd == 'trust':
            print(json.dumps({'trusted': ensure_trusted(a.project_path)}))
        else:
            print(json.dumps(start_rc(a.project_path, a.name, a.resume, a.permission_mode), indent=2))
    except RCError as e:
        print(json.dumps({'error': str(e)}))
        sys.exit(1)
