#!/usr/bin/env python3
"""
rc_sessions.py — start/resume Claude Code Remote Control sessions headlessly (OC-041).

Backs the Discord `rc` command: trust a folder, launch `claude --bg --remote-control`,
wait until the Remote Control bridge is up, and return the claude.ai link. Also lists a
project's past conversations, detects live sessions, stops them, and restores them
after a reboot.

Importable module + standalone CLI:
    python rc_sessions.py start <project_path> [--name N] [--resume SESSION_ID]
    python rc_sessions.py trust <project_path>
    python rc_sessions.py convos <project_path>
    python rc_sessions.py live

Verified facts (claude 2.1.289, 2026-10-05):
  - `claude --bg --remote-control -n NAME` runs with no terminal; prints
    "backgrounded · <jobId>"; the session's ~/.claude/sessions/<pid>.json gets
    a `bridgeSessionId` once Remote Control is connected. jobId = sessionId[:8].
  - `--bg --resume <id> --remote-control` on a non-running conversation (terminal or
    print-mode) continues the SAME session id.
  - `--bg --resume <id>` (no other flags) on a stopped bg session wakes it with its
    saved options; passing flags instead starts a COPY. Resuming a running session
    also starts a copy.
  - Untrusted folders fail with "Workspace not trusted"; setting
    ~/.claude.json projects["C:/fwd/slash/path"].hasTrustDialogAccepted=true fixes it.
  - Transcripts: ~/.claude/projects/<cwd with non-alnum -> '-'>/<sessionId>.jsonl;
    entrypoint 'cli' = terminal, 'sdk-cli' = print mode (Discord sub-sessions);
    titles in 'ai-title' entries.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

LOGDIR = Path(os.getenv('LOCALAPPDATA') or tempfile.gettempdir()) / 'openclaw'
CLAUDE_CONFIG = Path.home() / '.claude.json'
SESSIONS_DIR = Path.home() / '.claude' / 'sessions'
TRANSCRIPTS_DIR = Path.home() / '.claude' / 'projects'
REGISTRY_FILE = LOGDIR / 'rc-registry.json'
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

_config_lock = threading.Lock()
_registry_lock = threading.Lock()


class RCError(RuntimeError):
    """A Remote Control session could not be started or did not come up."""


class RCLiveElsewhere(RCError):
    """The conversation is running in a terminal without Remote Control."""

    def __init__(self, msg: str, status: str | None = None, pid: int | None = None):
        super().__init__(msg)
        self.status = status
        self.pid = pid


# ---------------------------------------------------------------------------
# Folder trust (~/.claude.json)
# ---------------------------------------------------------------------------

def config_key(project_path: str | Path) -> str:
    """Key used in ~/.claude.json `projects` (forward slashes, e.g. C:/Users/x/proj)."""
    return str(Path(project_path).resolve()).replace('\\', '/')


def _read_config(config_path: Path) -> dict:
    return json.loads(config_path.read_text(encoding='utf-8'))


def _stat_sig(path: Path) -> tuple[int, int]:
    st = path.stat()
    return st.st_mtime_ns, st.st_size


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
    """Mark folder trusted. Running claude processes also rewrite ~/.claude.json, so:
    skip the write if the file changed between our read and replace (would lose their
    update), and re-read afterwards in case they clobbered our flag."""
    key = config_key(project_path)
    with _config_lock:
        if is_trusted(project_path, config_path):
            log.debug('ensure_trusted: already trusted %s', key)
            return True
        for attempt in range(1, attempts + 1):
            tmp_name = None
            try:
                sig = _stat_sig(config_path)
                cfg = _read_config(config_path)
                cfg.setdefault('projects', {}).setdefault(key, {})['hasTrustDialogAccepted'] = True
                with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=config_path.parent,
                                                 prefix='.claude.json.rc-', delete=False) as tf:
                    tmp_name = tf.name
                    json.dump(cfg, tf, indent=2)
                if _stat_sig(config_path) != sig:
                    log.warning('ensure_trusted: %s changed during update (attempt %d), retrying',
                                config_path, attempt)
                    os.unlink(tmp_name)
                    time.sleep(0.5)
                    continue
                os.replace(tmp_name, config_path)
            except (OSError, json.JSONDecodeError) as e:
                log.warning('ensure_trusted: attempt %d write failed for %s: %s', attempt, key, e)
                if tmp_name and os.path.exists(tmp_name):
                    os.unlink(tmp_name)
                time.sleep(0.5)
                continue
            time.sleep(0.3)
            if is_trusted(project_path, config_path):
                log.info('ensure_trusted: trusted %s (attempt %d)', key, attempt)
                return True
            log.warning('ensure_trusted: flag lost after write for %s (attempt %d)', key, attempt)
    log.error('ensure_trusted: gave up on %s after %d attempts', key, attempts)
    return False


# ---------------------------------------------------------------------------
# claude CLI
# ---------------------------------------------------------------------------

def claude_exe() -> str:
    exe = shutil.which('claude')
    if not exe:
        raise RCError('claude CLI not found on PATH')
    return exe


_SAFE_NAME_RE = re.compile(r'[^\w.-]')


def safe_name(name: str) -> str:
    """Session display name safe for cmd.exe (claude is a .CMD on Windows)."""
    return _SAFE_NAME_RE.sub('_', name)[:64] or 'session'


def build_start_cmd(name: str, resume_id: str | None = None,
                    permission_mode: str = DEFAULT_PERMISSION_MODE) -> list[str]:
    cmd = [claude_exe(), '--bg']
    if resume_id:
        cmd += ['--resume', resume_id]
    cmd += ['--remote-control', '-n', safe_name(name), '--permission-mode', permission_mode]
    return cmd


def build_wake_cmd(session_id: str) -> list[str]:
    """Wake a stopped bg session with its saved options (flags would start a copy)."""
    return [claude_exe(), '--bg', '--resume', session_id]


_JOB_RE = re.compile(r'backgrounded\s*·\s*([0-9a-f]+)\b', re.IGNORECASE)


def parse_job_id(output: str) -> str | None:
    m = _JOB_RE.search(output)
    return m.group(1).lower() if m else None


def _run_claude(args: list[str], cwd: str | Path | None = None, timeout: float = 60) -> str:
    """Run a claude CLI command; returns stdout+stderr. Raises RCError on any failure to run."""
    try:
        r = subprocess.run(args, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=timeout,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        raise RCError(f'`claude {" ".join(args[1:3])}` did not return within {timeout}s') from e
    except (OSError, subprocess.SubprocessError) as e:
        raise RCError(f'could not run claude: {e}') from e
    out = (r.stdout or '') + (r.stderr or '')
    log.debug('claude %s -> rc=%s out=%r', args[1:], r.returncode, out[:500])
    return out


def logs_tail(job_id: str, lines: int = 15) -> str:
    """Last lines of `claude logs <id>`, ANSI stripped — for failure reports."""
    try:
        out = _run_claude([claude_exe(), 'logs', job_id], timeout=30)
    except RCError as e:
        return f'(could not read logs: {e})'
    out = re.sub(r'\x1b\[[0-9;?]*[A-Za-z]', '', out)
    kept = [ln.rstrip() for ln in out.splitlines() if ln.strip()]
    return '\n'.join(kept[-lines:])


def stop_job(job_id: str) -> str:
    try:
        out = _run_claude([claude_exe(), 'stop', job_id], timeout=30).strip()
    except RCError as e:
        out = f'stop failed: {e}'
    log.info('stop_job: %s -> %s', job_id, out[:200])
    return out


# ---------------------------------------------------------------------------
# Live sessions
# ---------------------------------------------------------------------------

def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if sys.platform == 'win32':
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def proc_start_time(pid: int) -> int | None:
    """Process creation time as a Windows FILETIME int (same units as the session
    record's `procStart`, verified 2026-10-05). None if unavailable."""
    if sys.platform != 'win32' or not pid:
        return None
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, int(pid))
    if not h:
        return None
    times = [wintypes.FILETIME() for _ in range(4)]
    ok = k32.GetProcessTimes(h, *[ctypes.byref(t) for t in times])
    k32.CloseHandle(h)
    if not ok:
        return None
    return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime


def record_is_live(rec: dict) -> bool:
    """pid alive AND (on Windows) it is the same process that wrote the record, so a
    stale record whose pid was reused by another program is never treated as live."""
    pid = rec.get('pid')
    if not pid_alive(pid):
        return False
    want = rec.get('procStart')
    if want is None or sys.platform != 'win32':
        return True
    try:
        return proc_start_time(pid) == int(want)
    except (TypeError, ValueError):
        return False


def session_records(sessions_dir: Path = SESSIONS_DIR, alive_only: bool = True) -> list[dict]:
    """Records from ~/.claude/sessions/*.json (one per running claude process)."""
    recs = []
    if not sessions_dir.exists():
        return recs
    for f in sessions_dir.glob('*.json'):
        try:
            rec = json.loads(f.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue  # file being rewritten by its owner; next poll will see it
        if alive_only and not record_is_live(rec):
            continue
        recs.append(rec)
    return recs


def find_session(job_id: str, sessions_dir: Path = SESSIONS_DIR) -> dict | None:
    """Return the ~/.claude/sessions/*.json record for a background job id, preferring the
    record of a live process (a dead one with the same id may still be on disk)."""
    matches = [r for r in session_records(sessions_dir, alive_only=False) if r.get('jobId') == job_id]
    live = [r for r in matches if record_is_live(r)]
    return (live or matches or [None])[0]


def _same_dir(a: str | Path, b: str | Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def live_in_dir(project_path: str | Path, sessions_dir: Path = SESSIONS_DIR) -> list[dict]:
    return [r for r in session_records(sessions_dir) if r.get('cwd') and _same_dir(r['cwd'], project_path)]


def live_rc_in_dir(project_path: str | Path, sessions_dir: Path = SESSIONS_DIR) -> list[dict]:
    """Live sessions in this folder with Remote Control connected. Cheap (no CLI call)."""
    return [r for r in live_in_dir(project_path, sessions_dir) if r.get('bridgeSessionId')]


def rc_url(rec: dict) -> str:
    return RC_URL_PREFIX + rec['bridgeSessionId']


def bg_session_ids() -> set[str]:
    """Session ids of all background sessions Claude knows about, any state. A bg session
    must be woken with no flags (flags start a copy)."""
    try:
        out = _run_claude([claude_exe(), 'agents', '--json', '--all'], timeout=30)
        items = json.loads(out[out.index('['):])
    except (RCError, ValueError) as e:
        log.warning('bg_session_ids: %s', e)
        return set()
    return {a['sessionId'] for a in items if a.get('kind') == 'background' and a.get('sessionId')}


def wait_for_bridge(job_id: str, timeout_s: float = 30, poll_s: float = 1,
                    sessions_dir: Path = SESSIONS_DIR) -> dict | None:
    """Poll until a LIVE session record has a bridgeSessionId. Returns the record or None.
    A dead process can leave its record (with bridgeSessionId) behind; accepting it reported
    "ready" for a session that was not running (found in the OC-043 live test)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        rec = find_session(job_id, sessions_dir)
        if rec and rec.get('bridgeSessionId') and record_is_live(rec):
            return rec
        time.sleep(poll_s)
    return None


# ---------------------------------------------------------------------------
# Registry of sessions started by the bot (for `rc restore` after reboot)
# ---------------------------------------------------------------------------

def _load_registry(path: Path = REGISTRY_FILE) -> dict:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_registry(reg: dict, path: Path = REGISTRY_FILE):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(reg, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def registry_add(session_id: str, cwd: str, name: str, path: Path = REGISTRY_FILE):
    with _registry_lock:
        reg = _load_registry(path)
        reg[session_id] = {'cwd': cwd, 'name': name, 'started': datetime.now().isoformat(timespec='seconds')}
        _save_registry(reg, path)


def registry_remove(session_id: str, path: Path = REGISTRY_FILE):
    with _registry_lock:
        reg = _load_registry(path)
        if reg.pop(session_id, None) is not None:
            _save_registry(reg, path)


def registry_entries(path: Path = REGISTRY_FILE) -> dict:
    return _load_registry(path)


# ---------------------------------------------------------------------------
# Conversations (transcripts)
# ---------------------------------------------------------------------------

def transcript_dir(project_path: str | Path, root: Path = TRANSCRIPTS_DIR) -> Path | None:
    """~/.claude/projects/<key>; key = absolute cwd with every non-alnum char -> '-'.
    Drive-letter case varies (e.g. 'c--Users-...'), so match case-insensitively."""
    key = re.sub(r'[^A-Za-z0-9]', '-', str(Path(project_path).resolve()))
    if not root.exists():
        return None
    exact = root / key
    if exact.is_dir():
        return exact
    for d in root.iterdir():
        if d.is_dir() and d.name.lower() == key.lower():
            return d
    return None


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ' '.join(b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text')
    return ''


def summarize_transcript(path: Path) -> dict:
    """Title, first prompt, user-turn count and source for one transcript."""
    title = first_prompt = ''
    user_turns = 0
    entrypoints = set()
    with path.open(encoding='utf-8', errors='replace') as fh:
        for ln in fh:
            try:
                o = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if not isinstance(o, dict):
                continue
            t = o.get('type')
            if o.get('entrypoint'):
                entrypoints.add(o['entrypoint'])
            if t in ('ai-title', 'custom-title'):
                title = o.get('aiTitle') or o.get('customTitle') or title
            elif t == 'user' and not o.get('isMeta') and not o.get('isSidechain'):
                text = _text_of((o.get('message') or {}).get('content')).strip()
                if text and not text.startswith('<'):  # skip tool results / command wrappers
                    user_turns += 1
                    if not first_prompt:
                        first_prompt = text
    if 'cli' in entrypoints:
        source = 'terminal'
    elif 'sdk-cli' in entrypoints:
        source = 'discord'
    else:
        source = 'unknown'
    return {
        'session_id': path.stem,
        'mtime': path.stat().st_mtime,
        'title': title,
        'first_prompt': re.sub(r'\s+', ' ', first_prompt)[:120],
        'user_turns': user_turns,
        'source': source,
    }


def list_conversations(project_path: str | Path, limit: int = 8, root: Path = TRANSCRIPTS_DIR) -> list[dict]:
    """Most recent conversations in a project folder, newest first. Empty ones are skipped."""
    d = transcript_dir(project_path, root)
    if not d:
        return []
    def _mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0  # deleted between glob and stat; summarize will skip it

    files = sorted(d.glob('*.jsonl'), key=_mtime, reverse=True)
    out = []
    for f in files:
        try:
            s = summarize_transcript(f)
        except OSError as e:
            log.warning('list_conversations: cannot read %s: %s', f, e)
            continue
        if s['user_turns'] == 0:
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


def create_project(root: str | Path, name: str) -> Path:
    """Case 1: make <root>/<name> with git + PROGRESS.md (PROGRESS.md makes
    project_list.discover_projects() list it under filtered roots)."""
    path = Path(root) / name
    if path.exists():
        raise RCError(f'`{path}` already exists - use `rc {name}` to open it.')
    path.mkdir(parents=True)
    (path / 'PROGRESS.md').write_text(
        f'# {name}' + chr(10) + chr(10) + f'- {datetime.now():%Y-%m-%d %H:%M} created from Discord via `rc create`' + chr(10),
        encoding='utf-8')
    try:
        subprocess.run(['git', 'init', '-q'], cwd=str(path), capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        log.warning('create_project: git init failed in %s: %s', path, e)
    log.info('create_project: created %s', path)
    return path


# ---------------------------------------------------------------------------
# Start / resume
# ---------------------------------------------------------------------------

def _result(rec: dict, job_id: str, name: str, project: Path, reused: bool = False) -> dict:
    return {
        'job_id': job_id,
        'session_id': rec.get('sessionId'),
        'bridge_session_id': rec['bridgeSessionId'],
        'url': rc_url(rec),
        'name': rec.get('name', name),
        'cwd': rec.get('cwd', str(project)),
        'reused': reused,
    }


def _launch_and_wait(cmd: list[str], project: Path, name: str, timeout_s: float) -> dict:
    t0_ms = time.time() * 1000
    try:
        out = _run_claude(cmd, cwd=project)
    except RCError:
        # The CLI may have started a session before hanging: stop anything new in this folder.
        for rec in live_in_dir(project):
            if rec.get('jobId') and rec.get('startedAt', 0) >= t0_ms - 1000:
                log.warning('launch failed; stopping orphan job %s', rec['jobId'])
                stop_job(rec['jobId'])
        raise
    if 'not trusted' in out.lower():
        raise RCError(f'workspace still not trusted: {out.strip()[:200]}')
    job_id = parse_job_id(out)
    if not job_id:
        raise RCError(f'could not parse job id: {out.strip()[:300]}')
    rec = wait_for_bridge(job_id, timeout_s)
    if not rec:
        tail = logs_tail(job_id)
        stopped = stop_job(job_id)  # don't leave an unreachable bypassPermissions session running
        log.error('no bridge for job=%s after %ss; stopped (%s); logs:\n%s', job_id, timeout_s, stopped, tail)
        raise RCError(f'session {job_id} started but Remote Control did not connect within '
                      f'{timeout_s}s, so it was stopped.\n{tail}')
    res = _result(rec, job_id, name, project)
    registry_add(res['session_id'], res['cwd'], res['name'])
    log.info('ready job=%s session=%s bridge=%s', job_id, res['session_id'], res['bridge_session_id'])
    return res


def start_rc(project_path: str | Path, name: str | None = None, resume_id: str | None = None,
             permission_mode: str = DEFAULT_PERMISSION_MODE, timeout_s: float = 30) -> dict:
    """Trust the folder, start a background Remote Control session, wait for the bridge.

    resume_id must NOT be a running session or a stopped bg session (use resume_rc,
    which handles those). Returns {job_id, session_id, bridge_session_id, url, name, cwd,
    reused}. Raises RCError.
    """
    project = Path(project_path)
    if not project.is_dir():
        raise RCError(f'project folder does not exist: {project}')
    name = name or project.name
    log.info('start_rc: project=%s name=%s resume=%s mode=%s', project, name, resume_id, permission_mode)
    if not ensure_trusted(project):
        raise RCError(f'could not mark {project} as trusted in {CLAUDE_CONFIG}')
    return _launch_and_wait(build_start_cmd(name, resume_id, permission_mode), project, name, timeout_s)


def resume_rc(project_path: str | Path, session_id: str, name: str | None = None,
              allow_copy: bool = False, timeout_s: float = 30) -> dict:
    """Bring one existing conversation up on Remote Control, picking the safe path:
      - already live with RC        -> return its link (reused=True)
      - live in a terminal, no RC   -> RCLiveElsewhere unless allow_copy (then a copy)
      - background session, not live -> wake with saved options (no flags);
                                       copy if that has no Remote Control
      - otherwise                   -> --resume <id> --remote-control (same id)
    """
    project = Path(project_path)
    if not project.is_dir():
        raise RCError(f'project folder does not exist: {project}')
    name = name or project.name
    live = [r for r in session_records() if r.get('sessionId') == session_id]
    if live:
        rec = live[0]
        if rec.get('bridgeSessionId'):
            log.info('resume_rc: %s already live with RC', session_id)
            return _result(rec, rec.get('jobId') or session_id[:8], name, project, reused=True)
        if not allow_copy:
            raise RCLiveElsewhere(f'conversation {session_id[:8]} is open in a terminal '
                                  f'(pid {rec.get("pid")}, {rec.get("status")}) without Remote Control',
                                  status=rec.get('status'), pid=rec.get('pid'))
        log.info('resume_rc: %s live without RC, starting a copy', session_id)
        return start_rc(project, name, resume_id=session_id, timeout_s=timeout_s)
    if not ensure_trusted(project):
        raise RCError(f'could not mark {project} as trusted in {CLAUDE_CONFIG}')
    if session_id in bg_session_ids():
        log.info('resume_rc: waking bg session %s with saved options', session_id)
        try:
            return _launch_and_wait(build_wake_cmd(session_id), project, name, timeout_s)
        except RCError as e:
            # Saved options had no --remote-control: a copy (with history) is the only way.
            # The original is not running, so the copy cannot diverge from a live session.
            log.warning('resume_rc: wake of %s gave no bridge (%s); starting a copy', session_id, e)
            res = start_rc(project, name, resume_id=session_id, timeout_s=timeout_s)
            res['copied'] = True
            registry_remove(session_id)  # the copy is now the one to restore
            return res
    return start_rc(project, name, resume_id=session_id, timeout_s=timeout_s)


def kill_pid(pid: int, wait_s: float = 10) -> bool:
    """Terminate a process tree and wait for it to exit. Returns True once it is gone."""
    if sys.platform == 'win32':
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, timeout=30)
    else:
        os.kill(pid, 15)
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.5)
    return not pid_alive(pid)


def takeover(project_path: str | Path, session_id: str, name: str | None = None,
             timeout_s: float = 30) -> dict:
    """Move a conversation that is open in a terminal (no Remote Control) onto Remote
    Control: end that terminal's claude process — only if it is idle, so no turn is cut
    off — then resume the same session id in the background with Remote Control."""
    live = [r for r in session_records() if r.get('sessionId') == session_id]
    if live:
        rec = live[0]
        if rec.get('bridgeSessionId'):
            return resume_rc(project_path, session_id, name, timeout_s=timeout_s)
        status = rec.get('status')
        if rec.get('kind') == 'bg' and rec.get('jobId'):
            log.info('takeover: stopping bg session %s (no RC) instead of killing', rec['jobId'])
            stop_job(rec['jobId'])
            deadline = time.monotonic() + 10
            while any(r.get('sessionId') == session_id for r in session_records()):
                if time.monotonic() > deadline:
                    raise RCError(f'background session {rec["jobId"]} did not stop within 10s')
                time.sleep(0.5)
            return resume_rc(project_path, session_id, name, timeout_s=timeout_s)
        if rec.get('kind') != 'interactive':
            raise RCError(f'session kind `{rec.get("kind")}` cannot be taken over \u2014 use `copy`.')
        if status != 'idle':
            raise RCError(f'the terminal session is `{status}`, not idle — not interrupting it. '
                          f'Try again when it has finished, or use `copy`.')
        if not record_is_live(rec):  # re-check identity right before killing
            raise RCError('terminal session changed while preparing takeover \u2014 try again.')
        log.warning('takeover: ending terminal claude pid=%s for session %s', rec.get('pid'), session_id)
        if not kill_pid(rec['pid']):
            raise RCError(f'could not end terminal process {rec["pid"]}')
    return resume_rc(project_path, session_id, name, timeout_s=timeout_s)


def stop_rc_in_dir(project_path: str | Path) -> list[str]:
    """Stop live RC background sessions in a folder (terminal sessions are left alone)."""
    stopped = []
    for rec in live_rc_in_dir(project_path):
        job = rec.get('jobId')
        if not job:
            continue
        stop_job(job)
        registry_remove(rec.get('sessionId', ''))
        stopped.append(rec.get('name') or job)
    return stopped


def terminal_rc_in_dir(project_path: str | Path, sessions_dir: Path = SESSIONS_DIR) -> list[dict]:
    """Live terminal (interactive) sessions in this folder with Remote Control on — the ones
    `stop_rc_in_dir` leaves alone. Closing them needs the user's explicit consent."""
    return [r for r in live_rc_in_dir(project_path, sessions_dir) if r.get('kind') == 'interactive']


def close_terminal(target: dict, force: bool = False, sessions_dir: Path = SESSIONS_DIR) -> str:
    """End the terminal claude process described by `target` ({pid, procStart, sessionId}).
    Without `force` it only closes an idle session, so no turn is cut off; `force` kills it
    whatever its status (for a hung session). The record is re-read and the process
    identity re-checked right before the kill. Returns the session name."""
    pid = target.get('pid')
    recs = [r for r in session_records(sessions_dir)
            if r.get('pid') == pid and r.get('sessionId') == target.get('sessionId')]
    name = target.get('name') or str(pid)
    if not recs:
        raise RCError(f'`{name}` is no longer running.')
    rec = recs[0]
    if target.get('procStart') is None or rec.get('procStart') is None:
        raise RCError(f'`{name}` has no process start time, so I can’t confirm it is the '
                      f'right process — not closing it.')
    if rec.get('procStart') != target['procStart']:
        raise RCError(f'`{name}` is a different process now — not closing it.')
    status = rec.get('status')
    if not force and status != 'idle':
        raise RCError(f'`{name}` is `{status}`, not idle — not interrupting it.')
    if not record_is_live(rec):  # re-check identity right before killing
        raise RCError(f'`{name}` changed while preparing to close it — try again.')
    log.warning('close_terminal: ending terminal claude pid=%s session=%s status=%s force=%s',
                pid, rec.get('sessionId'), status, force)
    if not kill_pid(pid):
        raise RCError(f'could not end terminal process {pid}')
    registry_remove(rec.get('sessionId', ''))
    return rec.get('name') or name


def close_terminals(targets: list[dict], force: bool = False) -> dict:
    """Close each target terminal session (see close_terminal). Status is re-checked at
    close time, not taken from when the question was asked. Returns {closed, failed,
    busy}: `busy` holds the targets left open because they were not idle (force=False)."""
    closed, failed, busy = [], [], []
    for t in targets:
        try:
            closed.append(close_terminal(t, force))
        except RCError as e:
            if not force and 'not idle' in str(e):
                busy.append(t)
            else:
                failed.append(str(e))
    return {'closed': closed, 'failed': failed, 'busy': busy}


def restore_all(timeout_s: float = 30) -> list[dict]:
    """Bring back every registry session that is no longer live (e.g. after a reboot)."""
    live_ids = {r.get('sessionId') for r in session_records()}
    results = []
    for sid, info in registry_entries().items():
        if sid in live_ids:
            continue
        try:
            res = resume_rc(info['cwd'], sid, info.get('name'), timeout_s=timeout_s)
            results.append({'name': info.get('name'), 'ok': True, 'url': res['url']})
        except RCError as e:
            log.error('restore_all: %s failed: %s', sid, e)
            results.append({'name': info.get('name'), 'ok': False, 'error': str(e)[:300]})
    return results


if __name__ == '__main__':
    import argparse

    ap = argparse.ArgumentParser(description='Remote Control session helper (OC-041)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('start')
    s.add_argument('project_path')
    s.add_argument('--name')
    s.add_argument('--resume')
    s.add_argument('--permission-mode', default=DEFAULT_PERMISSION_MODE)
    sub.add_parser('trust').add_argument('project_path')
    sub.add_parser('convos').add_argument('project_path')
    sub.add_parser('live')
    a = ap.parse_args()
    try:
        if a.cmd == 'trust':
            print(json.dumps({'trusted': ensure_trusted(a.project_path)}))
        elif a.cmd == 'convos':
            print(json.dumps(list_conversations(a.project_path), indent=2))
        elif a.cmd == 'live':
            print(json.dumps([{k: r.get(k) for k in ('jobId', 'sessionId', 'name', 'cwd', 'bridgeSessionId')}
                              for r in session_records()], indent=2))
        elif a.resume:
            print(json.dumps(resume_rc(a.project_path, a.resume, a.name), indent=2))
        else:
            print(json.dumps(start_rc(a.project_path, a.name, None, a.permission_mode), indent=2))
    except RCError as e:
        print(json.dumps({'error': str(e)}))
        sys.exit(1)
