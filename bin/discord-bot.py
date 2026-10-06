#!/usr/bin/env python3
import collections
import discord
import io
import subprocess
import os
import sys
import json
import logging
import asyncio
import glob
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Ensure stdout/stderr use UTF-8 under NSSM (default is cp1252 on Windows)
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

DELEGATE_PY = Path(__file__).parent / 'delegate.py'
LOCKFILE = Path(os.getenv('LOCALAPPDATA') or tempfile.gettempdir()) / 'openclaw' / 'discord-bot.lock'

# --- Single-instance guard: exit cleanly if another bot is already running ---
LOCKFILE.parent.mkdir(parents=True, exist_ok=True)
if sys.platform == 'win32':
    import msvcrt
    try:
        _lock_fh = open(LOCKFILE, 'w')
        msvcrt.locking(_lock_fh.fileno(), msvcrt.LK_NBLCK, 1)
    except (OSError, IOError):
        print('discord-bot: another instance is already running — exiting.', file=sys.stderr)
        sys.exit(0)
else:
    import fcntl
    try:
        _lock_fh = open(LOCKFILE, 'w')
        fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, IOError):
        print('discord-bot: another instance is already running — exiting.', file=sys.stderr)
        sys.exit(0)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%SZ'
)
log = logging.getLogger('discord-bot')

# ---------------------------------------------------------------------------
# Timeline logging (JSONL + human-readable)
# ---------------------------------------------------------------------------

_msg_counter = 0


def _new_session_id() -> str:
    """Short session ID: dm-XXXX (8 hex chars). Unique per Discord message."""
    return 'dm-' + uuid.uuid4().hex[:8]


def _ts_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime('%Y-%m-%dT%H:%M:%S.') + f'{now.microsecond // 1000:03d}Z'


def _tl(event: dict):
    """Append a JSONL event to the discord timeline log."""
    try:
        today = datetime.now().strftime('%Y-%m-%d')  # local time for file date
        tl_path = LOGDIR / f'discord-timeline-{today}.log'
        with open(tl_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(event) + '\n')
    except Exception:
        pass


def _log_human(text: str):
    """Append a human-readable line to the discord log."""
    try:
        today = datetime.now().strftime('%Y-%m-%d')  # local time for file date
        log_path = LOGDIR / f'discord-{today}.log'
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f'{now_str} {text}\n')
    except Exception:
        pass


with open(os.path.expanduser('~/.openclaw/openclaw.json')) as f:
    config = json.load(f)
token = config['channels']['discord']['token']
_gateway_token = config.get('gateway', {}).get('auth', {}).get('token', '')
_allow_from = config.get('channels', {}).get('discord', {}).get('allowFrom', [])
ALLOWED_USER = int(_allow_from[0]) if _allow_from else 1277144623231537274

CLAUDE_PROJECTS_DIR = os.path.expanduser('~/.claude/projects')

LOGDIR = Path(os.getenv('LOCALAPPDATA') or tempfile.gettempdir()) / 'openclaw'

# ---------------------------------------------------------------------------
# Log cleanup — delete log files older than 10 days on startup
# ---------------------------------------------------------------------------
LOG_RETENTION_DAYS = 10

def _cleanup_old_logs():
    """Delete log files older than LOG_RETENTION_DAYS."""
    from datetime import timedelta
    cutoff = datetime.now() - timedelta(days=LOG_RETENTION_DAYS)
    cutoff_str = cutoff.strftime('%Y-%m-%d')
    patterns = ['delegate-*-????-??-??.log', 'timeline-*-????-??-??.log',
                'discord-timeline-????-??-??.log', 'discord-????-??-??.log',
                'delegate-prompt-*.txt']
    removed = 0
    for pat in patterns:
        for f in LOGDIR.glob(pat):
            # Extract date from filename (last YYYY-MM-DD before .log/.txt)
            m = re.search(r'(\d{4}-\d{2}-\d{2})', f.name)
            if m and m.group(1) < cutoff_str:
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
    if removed:
        print(f'[startup] cleaned up {removed} log files older than {LOG_RETENTION_DAYS} days')

_cleanup_old_logs()

# ---------------------------------------------------------------------------
# Project discovery + slug matching (per-project concurrency)
# ---------------------------------------------------------------------------

from project_list import discover_projects

_known_projects: dict = {}  # lowercase_name -> full_path
_projects_refreshed_at: float = 0.0


def _refresh_projects():
    """Refresh known projects if >60s since last scan."""
    global _known_projects, _projects_refreshed_at
    now = time.monotonic()
    if now - _projects_refreshed_at > 60:
        _known_projects = discover_projects()
        _projects_refreshed_at = now


# ---------------------------------------------------------------------------
# Remote Control sessions (OC-041): deterministic `rc` command, bypasses triage
# ---------------------------------------------------------------------------

import rc_commands
import rc_sessions
from project_list import FILTERED_ROOTS, UNFILTERED_ROOTS

_rc_pending: dict = {}  # channel_id -> pending question (rc_commands.new_pending)


def _rc_roots() -> list[str]:
    return [str(r) for r in FILTERED_ROOTS + UNFILTERED_ROOTS if r.exists()]


async def _rc_run(message, sid: str, label: str, fn, *args):
    """Run a blocking rc_sessions call in a thread with a status message; report errors.
    Returns the call's result, or None on failure. RCLiveElsewhere propagates."""
    status = await message.reply(f'⏳ {label}…')
    t0 = time.monotonic()
    try:
        res = await asyncio.to_thread(fn, *args)
    except rc_sessions.RCLiveElsewhere:
        await status.delete()
        raise
    except Exception as e:  # RCError, or anything unexpected: never leave the status stuck
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'rc_failed', 'label': label,
             'error_type': type(e).__name__, 'error': str(e)[:500]})
        _log_human(f'[{sid}] RC FAILED ({label}): {str(e)[:200]}')
        log.error('[%s] rc failed (%s): %s', sid, label, e,
                  exc_info=not isinstance(e, rc_sessions.RCError))
        await status.edit(content=f'❌ {label} failed:\n```\n{str(e)[:1500]}\n```')
        return None
    if isinstance(res, dict) and res.get('url'):
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'rc_bridge_ready', 'label': label,
             'job_id': res['job_id'], 'session_id': res['session_id'],
             'bridge_session_id': res['bridge_session_id'], 'reused': res.get('reused', False),
             'copied': res.get('copied', False), 'elapsed_ms': int((time.monotonic() - t0) * 1000)})
        _log_human(f'[{sid}] RC ready ({label}): job={res["job_id"]} bridge={res["bridge_session_id"]}')
        await status.edit(content=rc_commands.format_ready(res))
    else:
        await status.delete()
    return res


async def _rc_resume(message, sid: str, ch: str, path: str, session_id: str, allow_copy: bool = False):
    name = Path(path).name
    try:
        await _rc_run(message, sid, f'Resuming `{session_id[:8]}` in `{name}`',
                      rc_sessions.resume_rc, path, session_id, name, allow_copy)
    except rc_sessions.RCLiveElsewhere as e:
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'rc_live_elsewhere', 'project': path,
             'session_id': session_id, 'status': e.status, 'pid': e.pid})
        # strict: if the router's request caused this question, only a plain "yes" consents
        _rc_pending[ch] = rc_commands.new_pending('elsewhere', path=path, session_id=session_id,
                                                  strict=getattr(message, 'from_router', False))
        await message.reply(rc_commands.format_live_elsewhere(name, e.status))


async def _rc_start_fresh(message, sid: str, path: str):
    name = Path(path).name
    await _rc_run(message, sid, f'Starting a fresh Remote Control session in `{name}`',
                  rc_sessions.start_rc, path, name)


async def _rc_open(message, sid: str, ch: str, path: str, arg: str | None):
    """`rc <project> [new|<n>]`: list conversations, or start/resume directly."""
    if arg == 'new':
        await _rc_start_fresh(message, sid, path)
        return
    convos = await asyncio.to_thread(rc_sessions.list_conversations, path)
    _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'rc_conversations', 'project': path,
         'count': len(convos), 'arg': arg})
    if not convos:
        await _rc_start_fresh(message, sid, path)
        return
    if arg is not None:
        n = int(arg)
        if n == 0:
            await _rc_start_fresh(message, sid, path)
        elif 1 <= n <= len(convos):
            await _rc_resume(message, sid, ch, path, convos[n - 1]['session_id'])
        else:
            await message.reply(f'Pick 0–{len(convos)}.\n{rc_commands.FOOTER}')
        return
    live = await asyncio.to_thread(rc_sessions.live_in_dir, path)
    live_rc = {r.get('sessionId') for r in live if r.get('bridgeSessionId')}
    live_other = {r.get('sessionId') for r in live if not r.get('bridgeSessionId')}
    _rc_pending[ch] = rc_commands.new_pending(
        'convo', path=path, project=Path(path).name.lower(),
        convos=[c['session_id'] for c in convos],
        labels=[f'{c["title"] or c["first_prompt"][:60] or "(untitled)"} '
                f'({datetime.fromtimestamp(c["mtime"]):%b %d}, {c["user_turns"]} msgs, {c["source"]})'
                for c in convos])
    await message.reply(rc_commands.format_conversations(Path(path).name, convos, live_rc, live_other))


async def _rc_create(message, sid: str, root: str, name: str):
    def _create_and_start():
        global _projects_refreshed_at
        path = rc_sessions.create_project(root, name)
        _projects_refreshed_at = 0.0  # next message rescans so the new project is known
        return rc_sessions.start_rc(path, name)

    await _rc_run(message, sid, f'Creating `{name}` in `{root}`', _create_and_start)


async def _rc_pick(message, sid: str, ch: str, n: int):
    pend = _rc_pending.pop(ch)
    if pend['kind'] == 'create':
        roots = pend['roots']
        if not 1 <= n <= len(roots):
            _rc_pending[ch] = pend
            await message.reply(f'Pick 1–{len(roots)}.\n{rc_commands.FOOTER}')
            return

        await _rc_create(message, sid, roots[n - 1], pend['name'])
    elif pend['kind'] == 'convo':
        ids = pend['convos']
        if n == 0:
            await _rc_start_fresh(message, sid, pend['path'])
        elif 1 <= n <= len(ids):
            await _rc_resume(message, sid, ch, pend['path'], ids[n - 1])
        else:
            _rc_pending[ch] = pend
            await message.reply(f'Pick 0–{len(ids)}.\n{rc_commands.FOOTER}')
    else:  # 'elsewhere' question pending: a number is not an answer, keep waiting
        _rc_pending[ch] = pend
        await message.reply(f'Reply `takeover` or `copy`, or ignore.\n{rc_commands.FOOTER}')


async def _handle_rc(message, act: dict, sid: str):
    """Entry point: never let an rc failure go unanswered."""
    try:
        await _handle_rc_inner(message, act, sid)
    except Exception as e:
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'rc_failed', 'label': act.get('action'),
             'error_type': type(e).__name__, 'error': str(e)[:500]})
        log.error('[%s] rc %s crashed: %s', sid, act.get('action'), e, exc_info=True)
        try:
            await message.reply(f'❌ `rc {act.get("action")}` failed: {type(e).__name__}: {str(e)[:500]}\n'
                                f'{rc_commands.FOOTER}')
        except Exception as e2:
            log.error('[%s] rc error reply failed: %s', sid, e2)


async def _handle_rc_inner(message, act: dict, sid: str):
    ch = str(message.channel.id)
    a = act['action']
    _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'rc_command', 'action': a,
         'project': act.get('project'), 'arg': act.get('arg'), 'n': act.get('n')})
    _log_human(f'[{sid}] RC command: {a} {act.get("project") or act.get("name") or act.get("n") or ""}')
    if a not in ('pick', 'copy', 'takeover'):
        # A new rc command supersedes any open question — except that a (possibly late) router
        # request must not wipe a takeover question the user is answering.
        if not (getattr(message, 'from_router', False)
                and _rc_pending.get(ch, {}).get('kind') == 'elsewhere'):
            _rc_pending.pop(ch, None)

    if a == 'help':
        await message.reply(rc_commands.USAGE)
    elif a == 'bad_name':
        await message.reply(f'`{act["name"]}` isn’t a valid folder name '
                            f'(letters, digits, `_ . -`).\n{rc_commands.FOOTER}')
    elif a == 'list':
        recs = await asyncio.to_thread(rc_sessions.session_records)
        live = [dict(r, url=rc_sessions.rc_url(r)) for r in recs if r.get('bridgeSessionId')]
        live_ids = {r.get('sessionId') for r in live}
        dormant = [dict(v, session_id=k) for k, v in rc_sessions.registry_entries().items()
                   if k not in live_ids]
        await message.reply(rc_commands.format_list(live, dormant))
    elif a == 'restore':
        res = await _rc_run(message, sid, 'Restoring Remote Control sessions', rc_sessions.restore_all)
        if res is not None:
            await message.reply(rc_commands.format_restore(res))
    elif a == 'create':
        roots = _rc_roots()
        if act.get('root'):  # rc create <name> <root#>
            if not 1 <= act['root'] <= len(roots):
                await message.reply(rc_commands.format_roots(act['name'], roots))
                _rc_pending[ch] = rc_commands.new_pending('create', name=act['name'], roots=roots)
                return
            await _rc_create(message, sid, roots[act['root'] - 1], act['name'])
            return
        _rc_pending[ch] = rc_commands.new_pending('create', name=act['name'], roots=roots)
        await message.reply(rc_commands.format_roots(act['name'], roots))
    elif a in ('stop', 'open') and not act.get('path'):
        if act['candidates']:  # so a plain-English answer ("the second one") gets context
            _rc_pending[ch] = rc_commands.new_pending('candidates', name=act['name'], action=a,
                                                      candidates=act['candidates'])
        await message.reply(rc_commands.format_candidates(act['name'], act['candidates']))
    elif a == 'stop':
        stopped = await asyncio.to_thread(rc_sessions.stop_rc_in_dir, act['path'])
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'rc_stopped', 'project': act['path'],
             'stopped': stopped})
        msg = ('⏹ Stopped: ' + ', '.join(f'`{n}`' for n in stopped)) if stopped else \
              'No Remote Control background sessions running there (terminal sessions are left alone).'
        await message.reply(f'{msg}\n{rc_commands.FOOTER}')
    elif a == 'open':
        await _rc_open(message, sid, ch, act['path'], act['arg'])
    elif a == 'pick':
        await _rc_pick(message, sid, ch, act['n'])
    elif a == 'copy':
        pend = _rc_pending.pop(ch)
        await _rc_resume(message, sid, ch, pend['path'], pend['session_id'], allow_copy=True)
    elif a == 'takeover':
        pend = _rc_pending.pop(ch)
        _log_human(f'[{sid}] RC takeover of {pend["session_id"][:8]} in {pend["path"]}')
        res = await _rc_run(message, sid, f'Taking over `{pend["session_id"][:8]}` in `{Path(pend["path"]).name}`',
                            rc_sessions.takeover, pend['path'], pend['session_id'], Path(pend['path']).name)
        if res is None:  # e.g. busy: keep the question open so `takeover`/`copy` still work
            _rc_pending[ch] = rc_commands.new_pending('elsewhere', path=pend['path'],
                                                      session_id=pend['session_id'])


# Common words that should never trigger prefix matching against project names
_PREFIX_BLOCKLIST = {'this', 'that', 'with', 'from', 'have', 'make', 'take', 'give',
                     'come', 'some', 'what', 'when', 'where', 'which', 'will', 'were',
                     'been', 'being', 'does', 'done', 'also', 'just', 'like', 'more',
                     'need', 'want', 'know', 'look', 'find', 'here', 'there', 'then',
                     'than', 'them', 'they', 'your', 'above', 'after', 'about', 'again',
                     'only', 'still', 'should', 'would', 'could', 'going', 'thing',
                     'every', 'write', 'check', 'start', 'stock', 'phase', 'change',
                     'claude', 'tests', 'test', 'step', 'same', 'send', 'open', 'close',
                     'screen', 'scree'}


def _match_project(message: str) -> str:
    """Match message words against project names. Return slug or 'router'.

    Matching strategy (in priority order):
    1. Exact whole-word match: message contains the full project name as a word
       e.g. "deploy shaadibot" matches "shaadibot"
    2. Fuzzy match: message words joined (no spaces/underscores) match project name
       e.g. "cricket analyzer" matches "cricketanalyzer" or "cricket_analyzer"
       e.g. "stock broker" matches "stockbroker"
    3. Prefix match: a message word is a prefix of a project name (min 4 chars)
       e.g. "shaadi" matches "shaadibot", "flight" matches "flightchecker"
       Blocked words (common English) are excluded from prefix matching.
    If exactly one project matches, return it. Otherwise return 'router'.
    """
    _refresh_projects()
    words = set(re.findall(r'\b\w+\b', message.lower()))

    # Pass 1: exact whole-word match
    exact = [name for name in _known_projects if name in words]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return 'router'

    # Pass 2: fuzzy — join adjacent words and match against normalized project names
    # e.g. "cricket analyzer" -> "cricketanalyzer" matches "cricketanalyzer" or "cricket_analyzer"
    msg_lower = message.lower()
    msg_joined = re.sub(r'[^a-z0-9]', '', msg_lower)
    fuzzy_matches = set()
    for name in _known_projects:
        normalized = name.replace('_', '').replace('-', '')
        if len(normalized) >= 6 and normalized in msg_joined:
            fuzzy_matches.add(name)
    if len(fuzzy_matches) == 1:
        return fuzzy_matches.pop()
    if len(fuzzy_matches) > 1:
        # Multiple matches — deduplicate by normalized name (same project, different dirs)
        by_norm = {}
        for name in fuzzy_matches:
            norm = name.replace('_', '').replace('-', '')
            by_norm.setdefault(norm, []).append(name)
        if len(by_norm) == 1:
            # All matches are the same logical project — pick the first
            return sorted(fuzzy_matches)[0]
        return 'router'

    # Pass 3: prefix match (word is a prefix of project name, min 4 chars)
    prefix_matches = set()
    for word in words:
        if len(word) < 4 or word in _PREFIX_BLOCKLIST:
            continue
        for name in _known_projects:
            if name.startswith(word) and name != word:
                prefix_matches.add(name)
    if len(prefix_matches) == 1:
        return prefix_matches.pop()
    return 'router'


# Per-project delegate tracking: slug -> PID
_running_delegates: dict = {}
_last_delegate_done_mono: float = 0.0  # monotonic time of last delegate completion

# Conversation continuity: channel_id -> (slug, monotonic_time)
# When slug matching returns "router" but a delegate finished recently for this channel,
# reuse the last slug (handles "On now", "Yes go ahead", "ok do it", etc.)
_last_channel_slug: dict = {}  # channel_id -> (slug, mono_time)
_CONTINUITY_WINDOW_S = 0  # Disabled — triage LLM handles context routing via recent messages


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        if sys.platform == 'win32':
            r = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'],
                               capture_output=True, text=True, timeout=5)
            return str(pid) in r.stdout
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Q&A triage — use LLM gateway (Haiku) to classify messages as ANSWER or DELEGATE.
# Simple questions get answered directly (~10-15s). Everything else goes to the
# full Claude router (~40-60s).
# ---------------------------------------------------------------------------

_GATEWAY_TRIAGE_URL = 'http://localhost:18789/ask'
_GATEWAY_TRIAGE_PROJECT = 'triage'


# Recent message buffer for triage context (last N messages per channel)
_recent_messages: dict = {}  # channel_id -> deque of (content, slug, timestamp)
_RECENT_MSG_LIMIT = 5


def _seed_recent_messages():
    """Seed _recent_messages from today's discord timeline so triage has context after restart."""
    today = datetime.now().strftime('%Y-%m-%d')
    tl_path = LOGDIR / f'discord-timeline-{today}.log'
    if not tl_path.exists():
        return
    try:
        lines = tl_path.read_text(encoding='utf-8', errors='replace').splitlines()
    except Exception:
        return
    # Collect message_received + delegate_spawn pairs to build (content, slug, ts)
    pending = {}  # sid -> (content, channel_id, ts)
    for line in lines:
        try:
            e = json.loads(line)
            evt = e.get('event', '')
            sid = e.get('sid', '')
            if evt == 'message_received' and sid:
                ch = str(e.get('channel_id', ''))
                pending[sid] = (e.get('content_preview', '')[:100], ch, e.get('ts', ''))
            elif evt == 'delegate_spawn' and sid and sid in pending:
                content, ch, ts = pending[sid]
                slug = e.get('slug', 'router')
                _recent_messages.setdefault(ch, collections.deque(maxlen=_RECENT_MSG_LIMIT))
                _recent_messages[ch].append((content, slug, ts))
            elif evt == 'qa_triage_done' and sid and sid in pending:
                content, ch, ts = pending[sid]
                slug = e.get('triage_slug', 'qa')
                decision = e.get('decision', '')
                if decision == 'answer':
                    slug = 'qa'
                _recent_messages.setdefault(ch, collections.deque(maxlen=_RECENT_MSG_LIMIT))
                _recent_messages[ch].append((content, slug, ts))
        except Exception:
            continue
    total = sum(len(v) for v in _recent_messages.values())
    if total:
        print(f'[startup] seeded {total} recent messages from {tl_path.name}')

_seed_recent_messages()


def _build_triage_prompt(content: str, channel_id: str) -> list[tuple[int, str]]:
    """Build triage prompt with numbered project list and recent messages.

    Returns (project_index_map, prompt_text):
      project_index_map: [(index, slug), ...] for resolving LLM response
    """
    _refresh_projects()
    sorted_projects = sorted(_known_projects.keys())
    # Build numbered list: 1=first project, 0=router (unsure)
    project_lines = []
    index_map: list[tuple[int, str]] = []
    for i, name in enumerate(sorted_projects, start=1):
        project_lines.append(f'{i}. {name}')
        index_map.append((i, name))

    projects_str = '\n'.join(project_lines)

    recent_lines = []
    recent = _recent_messages.get(channel_id, [])
    for msg_text, msg_slug, msg_ts in recent:
        slug_label = f' [{msg_slug}]' if msg_slug != 'router' else ''
        recent_lines.append(f'- {msg_text[:100]}{slug_label}')
    recent_str = '\n'.join(recent_lines) if recent_lines else '(none)'

    prompt = f'[PROJECTS]\n{projects_str}\n\n[RECENT]\n{recent_str}\n\n[MESSAGE]\n{content}'
    return index_map, prompt


async def _triage_message(content: str, channel_id: str) -> tuple[str, str | None, str]:
    """Call triage gateway project.

    Returns (decision, response_text, slug):
      ('answer', response_text, '') — bot replies directly
      ('delegate', None, slug)     — delegate to this slug (or 'router')
    """
    import urllib.request
    import urllib.error

    index_map, prompt_text = _build_triage_prompt(content, channel_id)

    def _call() -> tuple[str, str | None, str]:
        body = json.dumps({
            'project': _GATEWAY_TRIAGE_PROJECT,
            'message': prompt_text,
            'context': 'none',
        }).encode('utf-8')
        req = urllib.request.Request(
            _GATEWAY_TRIAGE_URL, data=body,
            headers={'Authorization': f'Bearer {_gateway_token}',
                     'Content-Type': 'application/json'},
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read())
                raw = (data.get('response') or '').strip()
                log.info('triage raw response: %s', raw[:200])
                if not raw:
                    return ('delegate', None, 'router')
                # Parse: first line is ANSWER or DELEGATE [slug]
                first_line = raw.split('\n', 1)[0].strip()
                first_upper = first_line.upper()
                if first_upper.startswith('DELEGATE'):
                    # Extract slug: "DELEGATE stockbroker" or "DELEGATE 3" -> slug
                    parts = first_line.split(None, 1)
                    raw_slug = parts[1].strip().lower() if len(parts) > 1 else 'router'
                    slug = raw_slug
                    # Resolve numbered response via index_map (0=router, 1..N=projects)
                    if raw_slug.isdigit():
                        num = int(raw_slug)
                        if num == 0:
                            slug = 'router'
                        else:
                            found = [s for i, s in index_map if i == num]
                            slug = found[0] if found else 'router'
                    # Validate slug against known projects
                    elif slug not in _known_projects and slug != 'router':
                        # Try prefix match
                        matches = [n for n in _known_projects if n.startswith(slug)]
                        if len(matches) == 1:
                            slug = matches[0]
                        else:
                            # Try fuzzy: remove spaces/hyphens and match
                            normalized = slug.replace(' ', '').replace('-', '')
                            for name in _known_projects:
                                if name.replace('-', '') == normalized:
                                    slug = name
                                    break
                            else:
                                slug = 'router'
                    log.info('triage slug: raw=%s resolved=%s', raw_slug, slug)
                    return ('delegate', None, slug)
                if first_upper == 'ANSWER':
                    answer = raw.split('\n', 1)[1].strip() if '\n' in raw else ''
                    return ('answer', answer, '') if answer else ('delegate', None, 'router')
                # Unrecognized format — delegate to be safe
                return ('delegate', None, 'router')
        except urllib.error.HTTPError as e:
            log.warning('gateway triage HTTP %d', e.code)
            return ('error', f'triage gateway HTTP {e.code}', 'router')
        except Exception as e:
            log.warning('gateway triage error: %s', e)
            return ('error', str(e)[:200], 'router')

    return await asyncio.to_thread(_call)


TOOL_ICONS = {
    'Bash': '\U0001f527', 'Edit': '\U0001f4dd', 'Read': '\U0001f4d6', 'Write': '\u270f\ufe0f',
    'Glob': '\U0001f50d', 'Grep': '\U0001f50d', 'WebFetch': '\U0001f310', 'WebSearch': '\U0001f310',
    'Task': '\U0001f916', 'TaskCreate': '\U0001f4cb', 'TaskUpdate': '\U0001f4cb',
    'TaskOutput': '\u23f3', 'Skill': '\u26a1', 'NotebookEdit': '\U0001f4d3',
    'TodoWrite': '\U0001f4cb',
}

# Multi-session tracking: slug -> session state
_active_sessions: dict = {}  # slug -> {session_data, status_events, start_mono, last_edit_ts}
_recent_msg_ids = collections.deque(maxlen=50)


def project_label(filepath):
    """Extract a short project name from a JSONL path."""
    dirname = os.path.basename(os.path.dirname(filepath))
    # e.g. -home-pranav-projects-screen-reader → screen-reader
    # Linux: -home-pranav-projects-<slug>
    for prefix in ['-home-pranav-projects-', '-home-pranav-']:
        if dirname.startswith(prefix):
            return dirname[len(prefix):]
    # Windows: try known root markers (most specific first)
    for marker in ['-AndroidStudioProjects-', '-PycharmProjects-', '-UnityProjects-',
                   '-projects-', '-Software-']:
        idx = dirname.find(marker)
        if idx != -1:
            return dirname[idx + len(marker):]
    return dirname


def _simplify_bash(command):
    """Strip noisy prefixes from bash commands to show the meaningful part."""
    if not command:
        return command
    # Split on && and take the last meaningful segment
    parts = command.split('&&')
    cmd = parts[-1].strip()
    # Strip cd, export prefixes from the last segment too
    while cmd.startswith(('cd ', 'export ')):
        # Find next && or ; separator
        for sep in ['&&', ';']:
            idx = cmd.find(sep)
            if idx != -1:
                cmd = cmd[idx + len(sep):].strip()
                break
        else:
            break
    # Simplify known script invocations
    # "python /d/.../discord-send.py --target ..." → "discord-send.py"
    # "bash /d/.../android-deploy.sh --project ..." → "android-deploy.sh --project ..."
    m = re.match(r'(?:python3?|bash)\s+\S*?([^/\\]+\.(?:py|sh))\b(.*)', cmd)
    if m:
        script = m.group(1)
        args = m.group(2).strip()
        # For discord-send.py, just show the script name (args are noise)
        if script == 'discord-send.py':
            return script
        return f'{script} {args}'.strip() if args else script
    # "./gradlew assembleDebug" → "gradlew assembleDebug"
    if cmd.startswith('./'):
        cmd = cmd[2:]
    return cmd

def _extract_tool_detail(name, inp):
    """Extract a clean, human-readable detail string for a tool invocation."""
    if not isinstance(inp, dict):
        return str(inp)[:100]
    if name in ('Read', 'Write', 'Edit'):
        fp = inp.get('file_path', '')
        return os.path.basename(fp) if fp else str(inp)[:100]
    if name == 'Bash':
        return _simplify_bash(inp.get('command', str(inp)[:100]))
    if name in ('Grep', 'Glob'):
        return inp.get('pattern', str(inp)[:100])
    if name == 'TaskCreate':
        return inp.get('subject', str(inp)[:100])
    if name == 'TaskUpdate':
        return inp.get('subject', inp.get('status', str(inp)[:100]))
    if name == 'TaskOutput':
        return 'checking task status'
    if name == 'Task':
        return inp.get('description', str(inp)[:100])
    if name == 'WebFetch':
        return inp.get('url', str(inp)[:100])
    if name == 'WebSearch':
        return inp.get('query', str(inp)[:100])
    if name == 'Skill':
        return inp.get('skill', str(inp)[:100])
    if name == 'TodoWrite':
        todos = inp.get('todos', [])
        if todos and isinstance(todos, list) and isinstance(todos[0], dict):
            return todos[0].get('content', str(inp)[:100])
        return str(inp)[:100]
    # Fallback
    return str(inp)[:100]


def format_entry(entry, project):
    """Return a list of log lines for a session JSONL entry, or empty list to skip."""
    msg = entry.get('message', {})
    role = msg.get('role', '')
    content = msg.get('content', [])

    if not content or not role:
        return []

    lines = []
    if isinstance(content, list):
        for c in content:
            if not isinstance(c, dict):
                continue
            ct = c.get('type', '')
            if ct == 'text':
                text = c.get('text', '').replace('\n', ' ').strip()
                if text:
                    lines.append(f'[{project}] [{role}] {text[:300]}')
            elif ct == 'tool_use':
                name = c.get('name', '')
                inp = c.get('input', {})
                detail = _extract_tool_detail(name, inp)
                lines.append(f'[{project}] [tool] {name}: {str(detail)[:200]}')
    elif isinstance(content, str):
        text = content.replace('\n', ' ').strip()
        if text:
            lines.append(f'[{project}] [{role}] {text[:300]}')

    return lines

async def _edit_status(session_data, status_events, elapsed_s, done=False, cancelled=False):
    """Edit the in-progress status message with current tool activity."""
    channel_id = int(session_data['target'])
    message_id = int(session_data['status_message_id'])
    project = session_data.get('project', 'openclaw')
    slug = session_data.get('slug', project)
    if cancelled:
        header = f'\u274c Cancelled \u00b7 `{elapsed_s}s` \u00b7 {slug}'
    elif done:
        header = f'\u2705 Done \u00b7 `{elapsed_s}s` \u00b7 {slug}'
    else:
        header = f'\U0001f504 Working\u2026 `{elapsed_s}s` \u00b7 {slug}'
    lines = [header]
    for ev in list(status_events)[-6:]:
        detail = ev['detail']
        if len(detail) > 90:
            detail = detail[:87] + '\u2026'
        if ev.get('type') == 'text':
            lines.append(f'-# \U0001f4ac {detail}')
        else:
            icon = TOOL_ICONS.get(ev.get('tool', ''), '\u2699\ufe0f')
            lines.append(f'-# {icon} {ev["tool"]} `{detail}`')
    try:
        ch = client.get_partial_messageable(channel_id)
        await ch.get_partial_message(message_id).edit(content='\n'.join(lines))
    except Exception as e:
        _tl({'ts': _ts_iso(), 'event': 'status_edit_failed', 'error': str(e)[:200],
             'channel_id': channel_id, 'message_id': message_id, 'slug': slug})
        log.warning('status edit failed for %s: %s', slug, e)


async def watch_claude_sessions():
    """Poll active-session-*.json files and ~/.claude/projects for new JSONL lines."""
    global _active_sessions
    file_positions = {}  # filepath -> byte offset

    # Seed all existing files at their current end so we only show new activity
    for path in glob.glob(f'{CLAUDE_PROJECTS_DIR}/**/*.jsonl', recursive=True):
        try:
            file_positions[path] = os.path.getsize(path)
        except OSError:
            pass

    while True:
        await asyncio.sleep(1)
        try:
            # --- Discover active sessions by globbing active-session-*.json ---
            current_slugs = set()
            for session_path in LOGDIR.glob('active-session-*.json'):
                try:
                    session_data = json.loads(session_path.read_text(encoding='utf-8'))
                    slug = session_data.get('slug', session_path.stem.replace('active-session-', ''))
                    # Max-age guard: clean up stale files (>2 hours)
                    ts_start = session_data.get('ts_start', '')
                    if ts_start:
                        try:
                            dt = datetime.fromisoformat(ts_start.replace('Z', '+00:00'))
                            if (datetime.now(timezone.utc) - dt).total_seconds() > 7200:
                                session_path.unlink(missing_ok=True)
                                continue
                        except (ValueError, OSError):
                            pass
                    current_slugs.add(slug)

                    if slug not in _active_sessions:
                        # New session detected
                        _active_sessions[slug] = {
                            'session_data': session_data,
                            'status_events': collections.deque(maxlen=20),
                            'start_mono': time.monotonic(),
                            'last_edit_ts': 0.0,
                        }
                        _tl({'ts': _ts_iso(), 'event': 'session_watcher_start',
                             'slug': slug,
                             'target': session_data.get('target', '?'),
                             'project': session_data.get('project', '?')})
                        # Re-seed file positions for new session
                        for p in glob.glob(f'{CLAUDE_PROJECTS_DIR}/**/*.jsonl', recursive=True):
                            try:
                                file_positions[p] = os.path.getsize(p)
                            except OSError:
                                pass
                    else:
                        # Update session data (project label may have changed)
                        _active_sessions[slug]['session_data'] = session_data
                except Exception:
                    continue

            # --- Detect finished sessions (slug was tracked but file is gone) ---
            finished_slugs = set(_active_sessions.keys()) - current_slugs
            for slug in finished_slugs:
                state = _active_sessions.pop(slug)
                elapsed = int(time.monotonic() - state['start_mono'])
                _tl({'ts': _ts_iso(), 'event': 'session_watcher_done',
                     'slug': slug,
                     'target': state['session_data'].get('target', '?'),
                     'project': state['session_data'].get('project', '?'),
                     'elapsed_s': elapsed})
                _log_human(f'Session done: slug={slug} elapsed={elapsed}s')
                await _edit_status(state['session_data'], state['status_events'], elapsed, done=True)
                # Clean up running delegate tracker
                _running_delegates.pop(slug, None)
                global _last_delegate_done_mono
                _last_delegate_done_mono = time.monotonic()
                # Track last slug per channel for conversation continuity
                ch = state['session_data'].get('target', '')
                if ch and slug not in ('router', 'default'):
                    _last_channel_slug[ch] = (slug, time.monotonic())

            # --- Scan JSONL files for new activity ---
            current_files = set(glob.glob(f'{CLAUDE_PROJECTS_DIR}/**/*.jsonl', recursive=True))

            for path in list(file_positions):
                if path not in current_files:
                    del file_positions[path]

            for path in current_files:
                if '/memory/' in path:
                    continue
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue

                last = file_positions.get(path)
                if last is None:
                    file_positions[path] = size
                    continue
                if size <= last:
                    continue

                try:
                    with open(path, 'rb') as f:
                        f.seek(last)
                        new_data = f.read()
                    file_positions[path] = size
                except OSError:
                    continue

                project = project_label(path)
                for line in new_data.decode('utf-8', errors='replace').splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        for msg_line in format_entry(entry, project):
                            print(msg_line, flush=True)
                            # Route status events to the matching active session.
                            # Match by cwd_label (the WORK_DIR name that delegate.py wrote).
                            # This prevents terminal Claude sessions from leaking into Discord status.
                            # No fallback — unmatched events are simply not routed.
                            target_slug = None
                            for s_slug, s_state in _active_sessions.items():
                                cwd_label = s_state['session_data'].get('cwd_label', '')
                                if cwd_label and cwd_label.lower() == project.lower():
                                    target_slug = s_slug
                                    break

                            if target_slug and target_slug in _active_sessions:
                                s_state = _active_sessions[target_slug]
                                if '[tool]' in msg_line:
                                    parts = msg_line.split('] [tool] ', 1)
                                    if len(parts) == 2:
                                        tool_name, _, detail = parts[1].partition(': ')
                                        s_state['status_events'].append({
                                            'type': 'tool',
                                            'tool': tool_name.strip(),
                                            'detail': detail.strip(),
                                        })
                                elif '[assistant]' in msg_line:
                                    parts = msg_line.split('] [assistant] ', 1)
                                    if len(parts) == 2:
                                        text = parts[1].strip()
                                        if text:
                                            s_state['status_events'].append({
                                                'type': 'text',
                                                'detail': text,
                                            })
                    except json.JSONDecodeError:
                        pass

            # --- Throttled status message edits (~every 3s, staggered across sessions) ---
            # Discord rejects edits to messages older than 1 hour (429 error code 30046).
            # Skip edits for sessions running longer than 55 minutes to avoid spam.
            MAX_EDIT_AGE_S = 55 * 60  # 55 minutes (5min safety margin before Discord's 1hr limit)
            now = time.monotonic()
            for slug, state in _active_sessions.items():
                if (now - state['last_edit_ts']) >= 3.0:
                    elapsed = int(now - state['start_mono'])
                    if elapsed > MAX_EDIT_AGE_S:
                        continue  # Skip — Discord won't accept edits to old messages
                    await _edit_status(state['session_data'], state['status_events'], elapsed)
                    state['last_edit_ts'] = now
                    break  # Only edit one session per tick to avoid Discord rate limits

        except Exception as e:
            _tl({'ts': _ts_iso(), 'event': 'session_watcher_error', 'error': str(e)[:200]})
            log.error('session watcher error: %s', e)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

RC_REQUEST_DIR = LOGDIR / 'rc-requests'
_RC_REQUEST_MAX_AGE_S = 300
_rc_watcher_started = False
_RC_REQUEST_MAX_PER_MIN = 5
_rc_request_times: collections.deque = collections.deque()


class _ChannelReplier:
    """Minimal stand-in for a discord.Message so _handle_rc can answer router requests."""

    from_router = True  # stricter consent + don't clobber the user's open question

    def __init__(self, channel):
        self.channel = channel

    async def reply(self, text):
        return await self.channel.send(text)


async def _process_rc_request(req: dict):
    """OC-043: run one rc command the router translated from natural language."""
    sid = _new_session_id()
    cmd = str(req.get('command', ''))[:200]
    ch_id = str(req.get('channel', ''))
    age = time.time() - float(req.get('ts', 0) or 0)
    _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'rc_request_received', 'command': cmd,
         'channel_id': ch_id, 'age_s': int(age), 'request_id': req.get('id')})
    _log_human(f'[{sid}] RC request from router: {cmd!r}')

    def _reject(reason: str):
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'rc_request_rejected', 'command': cmd, 'reason': reason})
        log.warning('[%s] rc request rejected (%s): %r', sid, reason, cmd)

    if age > _RC_REQUEST_MAX_AGE_S:
        _reject('stale')
        return
    if req.get('source') != 'router':
        _reject('unknown source')
        return
    now = time.monotonic()
    while _rc_request_times and now - _rc_request_times[0] > 60:
        _rc_request_times.popleft()
    if len(_rc_request_times) >= _RC_REQUEST_MAX_PER_MIN:  # a looping LLM can't flood actions
        _reject('rate limit')
        return
    _rc_request_times.append(now)
    try:
        channel = client.get_channel(int(ch_id)) or await client.fetch_channel(int(ch_id))
    except Exception as e:
        _reject(f'channel: {e}')
        return
    recipient = getattr(channel, 'recipient', None)
    if not isinstance(channel, discord.DMChannel) or not recipient or recipient.id != ALLOWED_USER:
        _reject('not the allowed user DM')
        return
    global _projects_refreshed_at
    _projects_refreshed_at = 0.0  # the router may have just created the project (android-new.sh)
    _refresh_projects()
    act = rc_commands.parse(cmd, _known_projects, None)
    if not act:
        _reject('not a valid rc command')
        await channel.send(f'I tried `{cmd}` but that isn’t a valid rc command. '
                           f'Send `rc` for the list.\n{rc_commands.FOOTER}')
        return
    if act['action'] in rc_commands.ROUTER_FORBIDDEN:
        _reject(f'forbidden action {act["action"]}')
        await channel.send(f'That needs your own answer — reply `yes`, `takeover` or `copy` '
                           f'to the question above.\n{rc_commands.FOOTER}')
        return
    _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'rc_request_accepted', 'action': act['action']})
    await _handle_rc(_ChannelReplier(channel), act, sid)


async def watch_rc_requests():
    """Pick up rc_request.py files (one JSON each) and run them in order."""
    RC_REQUEST_DIR.mkdir(parents=True, exist_ok=True)
    while True:
        await asyncio.sleep(1)
        for f in sorted(RC_REQUEST_DIR.glob('*.json')):
            try:
                req = json.loads(f.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError) as e:
                log.warning('rc request %s unreadable: %s', f.name, e)
                req = None
            try:
                f.unlink()
            except OSError as e:
                log.warning('rc request %s could not be removed: %s', f.name, e)
                continue  # don't run it again next poll
            if isinstance(req, dict):
                try:
                    await _process_rc_request(req)
                except Exception as e:
                    log.error('rc request %s failed: %s', f.name, e, exc_info=True)


RESTART_SIGNAL_FILE = LOGDIR / 'restart-bot.signal'


async def watch_restart_signal():
    """Exit cleanly when restart-bot.py drops a signal file. run-bot.cmd (OC-042) restarts it."""
    while True:
        await asyncio.sleep(2)
        if RESTART_SIGNAL_FILE.exists():
            try:
                RESTART_SIGNAL_FILE.unlink()
            except Exception:
                pass
            _tl({'ts': _ts_iso(), 'event': 'restart_signal_received'})
            _log_human('Restart signal received — exiting for run-bot.cmd restart')
            log.info('restart signal received — exiting for run-bot.cmd restart')
            os._exit(0)


@client.event
async def on_ready():
    log.info('ready user=%s id=%s', client.user, client.user.id)
    _tl({'ts': _ts_iso(), 'event': 'bot_ready', 'user': str(client.user), 'user_id': client.user.id})
    _log_human(f'Bot ready: {client.user} (id={client.user.id})')
    asyncio.create_task(watch_claude_sessions())
    asyncio.create_task(watch_restart_signal())
    global _rc_watcher_started
    if not _rc_watcher_started:  # on_ready fires again on reconnect; one watcher only
        _rc_watcher_started = True
        asyncio.create_task(watch_rc_requests())
    log.info('session watcher started')

@client.event
async def on_message(message):
    global _msg_counter

    if message.author.bot:
        return
    if message.author.id != ALLOWED_USER:
        _tl({'ts': _ts_iso(), 'event': 'message_ignored', 'reason': 'wrong_user',
             'author_id': message.author.id, 'channel_type': type(message.channel).__name__})
        log.info('ignored author=%s channel_type=%s', message.author.id, type(message.channel).__name__)
        return
    if not isinstance(message.channel, discord.DMChannel):
        _tl({'ts': _ts_iso(), 'event': 'message_ignored', 'reason': 'not_dm',
             'author_id': message.author.id, 'channel_type': type(message.channel).__name__})
        log.info('ignored non-dm author=%s channel_type=%s', message.author.id, type(message.channel).__name__)
        return

    # Deduplicate: Discord gateway may deliver the same message multiple times
    if message.id in _recent_msg_ids:
        _tl({'ts': _ts_iso(), 'event': 'message_deduplicated', 'message_id': message.id})
        log.info('ignored duplicate message id=%s', message.id)
        return
    _recent_msg_ids.append(message.id)

    _msg_counter += 1
    sid = _new_session_id()
    t0 = time.monotonic()
    content = message.content.replace('\n', ' ')

    _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'message_received', 'num': _msg_counter,
         'message_id': message.id, 'author_id': message.author.id,
         'channel_id': message.channel.id, 'msg_len': len(content),
         'attachment_count': len(message.attachments),
         'content_preview': content[:200]})
    _log_human(f'[{sid}] Message #{_msg_counter} from {message.author} (id={message.author.id}): '
               f'{content[:150]}{"…" if len(content) > 150 else ""}')

    # Handle "stop" / "cancel" command — writes stop signal for ALL running delegates
    if content.strip().lower() in ('stop', 'cancel'):
        try:
            # Write global stop signal (backwards compat)
            stop_signal = LOGDIR / 'stop.signal'
            stop_signal.write_text('1', encoding='utf-8')
            # Also write per-slug stop signals for all running delegates
            stopped_slugs = []
            for slug_name in list(_running_delegates.keys()):
                per_slug_signal = LOGDIR / f'stop-{slug_name}.signal'
                per_slug_signal.write_text('1', encoding='utf-8')
                stopped_slugs.append(slug_name)
            _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'stop_signal', 'status': 'written',
                 'stopped_slugs': stopped_slugs})
            _log_human(f'[{sid}] Stop signal written for: {stopped_slugs or ["global"]}')
            log.info('[%s] stop signal written for %s', sid, stopped_slugs or ['global'])
            await message.reply('\u23f9\ufe0f Cancelling\u2026')
        except Exception as e:
            _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'stop_signal', 'status': 'failed', 'error': str(e)[:200]})
            log.error('[%s] stop signal failed: %s', sid, e)
            await message.reply(f'Failed to stop: {e}')
        return

    # Remote Control command (OC-041) — deterministic, bypasses triage
    _refresh_projects()
    _rc_act = rc_commands.parse(content, _known_projects, _rc_pending.get(str(message.channel.id)))
    if _rc_act:
        await _handle_rc(message, _rc_act, sid)
        return
    # Any non-rc message closes an open rc question, so a later bare "2" meant for
    # something else can never start a session. OC-043: the question is handed to the
    # router once, so a plain-English answer ("the login one") can still be resolved —
    # or, if the user changed topic, the router just handles the new request.
    _rc_popped = _rc_pending.pop(str(message.channel.id), None)
    _rc_ctx = rc_commands.pending_context(_rc_popped)
    if _rc_ctx and content.startswith('!'):
        _rc_ctx = ''  # "!" = explicit Discord pipeline; not an answer to the rc question
    if _rc_ctx:
        # Topic switch: the reply names a project unrelated to the question -> normal routing
        _named = _match_project(content)
        _related = {_rc_popped.get('project'), *(_rc_popped.get('candidates') or [])}
        if _named != 'router' and _named not in _related:
            _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'rc_pending_topic_switch', 'slug': _named})
            _rc_ctx = ''
    if _rc_ctx:
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'rc_pending_to_router', 'context_len': len(_rc_ctx)})
        _log_human(f'[{sid}] RC question open — sending reply to router with context')
    # "!" prefix: send through the Discord pipeline even if the project is live on RC
    _force_discord = content.startswith('!')
    if _force_discord:
        content = content[1:].lstrip()

    env = None  # inherit environment; claude is already in PATH

    # Download attachments if any
    attach_count = 0
    attach_paths = []
    if message.attachments:
        attach_dir = Path(tempfile.gettempdir()) / 'openclaw' / 'attachments' / str(message.id)
        attach_dir.mkdir(parents=True, exist_ok=True)
        for att in message.attachments:
            dest = attach_dir / att.filename
            await att.save(str(dest))
            attach_paths.append(str(dest))
        env = {**os.environ, 'DELEGATE_ATTACHMENTS': ','.join(attach_paths)}
        attach_count = len(attach_paths)
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'attachments_downloaded',
             'count': attach_count, 'filenames': [a.filename for a in message.attachments],
             'total_bytes': sum(a.size for a in message.attachments)})
        _log_human(f'[{sid}] Downloaded {attach_count} attachments')

    # --- Q&A triage: ask LLM whether to answer directly or delegate ---
    # Always runs when gateway token is configured (no cooldown, no message-length limit).
    # Skip triage when attachments are present — always delegate (triage can't see files).
    decision = ''  # 'answer', 'delegate', 'error', or '' if triage skipped
    triage_slug = ''
    if _gateway_token and not attach_count and not _rc_ctx:
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'qa_triage_attempt',
             'msg_len': len(content), 'content_preview': content[:100]})
        _log_human(f'[{sid}] Q&A triage: asking gateway')
        ch_key = str(message.channel.id)
        decision, resp, triage_slug = await _triage_message(content, ch_key)
        if decision == 'answer' and resp:
            watermarked = resp.strip()
            # Add watermark if not already present
            if not watermarked.endswith('-# sent by claude'):
                watermarked += '\n-# sent by claude'
            try:
                await message.reply(watermarked)
            except Exception as e:
                log.warning('[%s] qa triage reply failed: %s', sid, e)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'qa_triage_done',
                 'decision': 'answer', 'response_len': len(resp), 'elapsed_ms': elapsed_ms})
            _log_human(f'[{sid}] Q&A triage: ANSWER ({elapsed_ms}ms, {len(resp)}ch)')
            # Record in recent messages
            _recent_messages.setdefault(ch_key, collections.deque(maxlen=_RECENT_MSG_LIMIT))
            _recent_messages[ch_key].append((content[:100], 'qa', _ts_iso()))
            return
        # Triage said DELEGATE or errored — use slug hint and fall through
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'qa_triage_done',
             'decision': decision, 'triage_slug': triage_slug, 'elapsed_ms': elapsed_ms})
        if decision == 'error':
            _log_human(f'[{sid}] Q&A triage: ERROR {resp} ({elapsed_ms}ms) — falling back to keyword routing')
        else:
            _log_human(f'[{sid}] Q&A triage: DELEGATE slug={triage_slug} ({elapsed_ms}ms)')
    elif attach_count:
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'qa_triage_skipped',
             'reason': 'attachments', 'attachment_count': attach_count})
        _log_human(f'[{sid}] Q&A triage: skipped (has {attach_count} attachments)')

    # --- Project slug matching + per-project concurrency ---
    # Priority: keyword match > triage slug > continuity fallback > router
    # Keyword match is most reliable when it fires (explicit project name in message).
    # Triage has context but can misidentify follow-ups; continuity catches the rest.
    _ch = str(message.channel.id)
    # OC-043: an answer to an open rc question always goes to the router (not a project)
    keyword_slug = 'router' if _rc_ctx else _match_project(content)
    if keyword_slug != 'router':
        slug = keyword_slug
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'slug_from_keyword', 'slug': slug})
        _log_human(f'[{sid}] Slug from keyword: {slug}')
    elif triage_slug and triage_slug != 'router' and triage_slug in _known_projects:
        slug = triage_slug
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'slug_from_triage', 'slug': slug})
        _log_human(f'[{sid}] Slug from triage: {slug}')
    else:
        # Neither keyword nor triage identified a specific project — use continuity.
        # Activates when: (a) triage returned 'router', (b) triage errored, (c) no triage.
        # Previously only activated on triage error — now handles all no-match cases so
        # follow-ups like "Yes go ahead" work even when triage can't identify the project.
        slug = 'router'
        if _ch in _last_channel_slug and not _rc_ctx:
            _last_slug, _last_mono = _last_channel_slug[_ch]
            _elapsed = time.monotonic() - _last_mono
            if _elapsed < 600 and _last_slug in _known_projects:
                slug = _last_slug
                reason = 'triage_error' if decision == 'error' else 'triage_no_match'
                _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'slug_continuity_fallback',
                     'slug': slug, 'elapsed_s': int(_elapsed), 'reason': reason})
                _log_human(f'[{sid}] Continuity fallback ({reason}): slug={slug} ({int(_elapsed)}s ago)')

    # OC-041 guard: project has a live Remote Control session -> point there instead of
    # running a second writer (delegate --continue) on the same conversation folder.
    # Only for explicitly identified projects (keyword/triage, not continuity guesses),
    # and never when attachments were sent (they would be dropped).
    _slug_explicit = keyword_slug != 'router' or slug == triage_slug
    if slug in _known_projects and _slug_explicit and not attach_count and not _force_discord:
        _rc_live = rc_sessions.live_rc_in_dir(_known_projects[slug])
        if _rc_live:
            _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'rc_guard_redirect', 'slug': slug,
                 'session_id': _rc_live[0].get('sessionId')})
            _log_human(f'[{sid}] RC guard: {slug} live on Remote Control, not delegating')
            await message.reply(rc_commands.format_guard(slug, rc_sessions.rc_url(_rc_live[0])))
            return

    # OC-043: an answer to an rc question must not be dropped just because the router run
    # that asked it is still exiting — wait up to 60s for that run to finish.
    if _rc_ctx and slug in _running_delegates:
        for _ in range(30):
            if not await asyncio.to_thread(_is_pid_alive, _running_delegates[slug]):
                break
            await asyncio.sleep(2)
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'rc_wait_router',
             'still_busy': await asyncio.to_thread(_is_pid_alive, _running_delegates[slug])})

    # Check if this slug already has a running delegate
    if slug in _running_delegates:
        old_pid = _running_delegates[slug]
        if _is_pid_alive(old_pid):
            _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'delegate_busy',
                 'slug': slug, 'existing_pid': old_pid})
            _log_human(f'[{sid}] Slug {slug} busy (pid={old_pid})')
            log.info('[%s] slug=%s busy pid=%d', sid, slug, old_pid)
            if _rc_ctx and _rc_popped:  # keep the rc question so the resend still has context
                _rc_pending[str(message.channel.id)] = _rc_popped
            await message.reply(f'Still working on `{slug}` \u2014 please resend in a moment.')
            return
        else:
            # Stale PID, clean up
            del _running_delegates[slug]

    log.info('[%s] dispatch channel=%s slug=%s msg_len=%d attachments=%d', sid, message.channel.id, slug, len(content), attach_count)

    try:
        if _force_discord:  # "!" prefix: let agent-smart's RC guard (OC-041) allow --continue
            env = {**(env or os.environ), 'OPENCLAW_FORCE_DISCORD': '1'}
        if _rc_ctx:  # OC-043: delegate.py adds this to the router prompt
            env = {**(env or os.environ), 'OPENCLAW_RC_PENDING': _rc_ctx}
        cmd = [sys.executable, str(DELEGATE_PY), 'discord', str(message.channel.id),
               '--slug', slug, content]
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'delegate_spawn',
             'slug': slug,
             'command': [os.path.basename(sys.executable), os.path.basename(str(DELEGATE_PY)),
                         'discord', str(message.channel.id), '--slug', slug, content[:200]],
             'has_attachments': attach_count > 0})
        if sys.platform == 'win32':
            proc = subprocess.Popen(
                cmd, env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
            )
        else:
            proc = subprocess.Popen(
                cmd, env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        _running_delegates[slug] = proc.pid
        # Record slug for conversation continuity (even before it finishes)
        if slug not in ('router', 'default'):
            _last_channel_slug[str(message.channel.id)] = (slug, time.monotonic())
        # Record in recent messages for triage context
        ch_key = str(message.channel.id)
        _recent_messages.setdefault(ch_key, collections.deque(maxlen=_RECENT_MSG_LIMIT))
        _recent_messages[ch_key].append((content[:100], slug, _ts_iso()))
        duration_ms = int((time.monotonic() - t0) * 1000)
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'delegate_spawned',
             'slug': slug, 'pid': proc.pid, 'dispatch_ms': duration_ms})
        _log_human(f'[{sid}] Delegate spawned slug={slug} pid={proc.pid} ({duration_ms}ms)')
        log.info('[%s] delegate slug=%s pid=%d', sid, slug, proc.pid)
    except Exception as e:
        duration_ms = int((time.monotonic() - t0) * 1000)
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'delegate_spawn_failed',
             'slug': slug, 'error': str(e)[:200], 'duration_ms': duration_ms})
        _log_human(f'[{sid}] Delegate spawn FAILED (slug={slug}): {e}')
        log.error('[%s] delegate slug=%s spawn failed: %s', sid, slug, e)

client.run(token)
