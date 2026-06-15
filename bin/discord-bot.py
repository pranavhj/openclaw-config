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
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        tl_path = LOGDIR / f'discord-timeline-{today}.log'
        with open(tl_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(event) + '\n')
    except Exception:
        pass


def _log_human(text: str):
    """Append a human-readable line to the discord log."""
    try:
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
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
ALLOWED_USER = 1277144623231537274

CLAUDE_PROJECTS_DIR = os.path.expanduser('~/.claude/projects')

LOGDIR = Path(os.getenv('LOCALAPPDATA') or tempfile.gettempdir()) / 'openclaw'

# ---------------------------------------------------------------------------
# Project discovery + slug matching (per-project concurrency)
# ---------------------------------------------------------------------------

FILTERED_ROOTS = [
    Path.home() / 'projects',
    Path.home() / 'AndroidStudioProjects',
    Path.home() / 'PycharmProjects',
    Path.home() / 'UnityProjects',
]
UNFILTERED_ROOTS = [
    Path('D:/MyData/Software'),
]
EXCLUDE_NAMES: set = set()

_known_projects: dict = {}  # lowercase_name -> full_path
_projects_refreshed_at: float = 0.0


def _discover_projects() -> dict:
    """Return {lowercase_name: full_path} for known projects."""
    projects = {}
    for root in FILTERED_ROOTS:
        if not root.exists():
            continue
        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.name in EXCLUDE_NAMES:
                continue
            if (d / '.claude').exists() or (d / 'PROGRESS.md').exists():
                projects[d.name.lower()] = str(d)
    for root in UNFILTERED_ROOTS:
        if not root.exists():
            continue
        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.name in EXCLUDE_NAMES:
                continue
            projects[d.name.lower()] = str(d)
    return projects


def _refresh_projects():
    """Refresh known projects if >60s since last scan."""
    global _known_projects, _projects_refreshed_at
    now = time.monotonic()
    if now - _projects_refreshed_at > 60:
        _known_projects = _discover_projects()
        _projects_refreshed_at = now


def _match_project(message: str) -> str:
    """Match message words against project names. Return slug or 'router'.

    Matching strategy (in priority order):
    1. Exact whole-word match: message contains the full project name as a word
       e.g. "deploy shaadibot" matches "shaadibot"
    2. Prefix match: a message word is a prefix of a project name (min 4 chars)
       e.g. "shaadi" matches "shaadibot", "flight" matches "flightchecker"
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

    # Pass 2: prefix match (word is a prefix of project name, min 4 chars)
    prefix_matches = set()
    for word in words:
        if len(word) < 4:
            continue
        for name in _known_projects:
            if name.startswith(word) and name != word:
                prefix_matches.add(name)
    if len(prefix_matches) == 1:
        return prefix_matches.pop()
    return 'router'


# Per-project delegate tracking: slug -> PID
_running_delegates: dict = {}


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
# Q&A fast path — route simple general-knowledge questions through LLM gateway
# (Haiku, ~10-15s) instead of the full Claude router (~40-60s).
# ---------------------------------------------------------------------------

_QA_STARTERS = {'what', 'why', 'how', 'when', 'where', 'who', 'can', 'does', 'is', 'are',
                'should', 'did', 'has', 'have', 'explain', 'tell'}
_ACTION_STARTERS = {'fix', 'add', 'update', 'create', 'build', 'deploy', 'run', 'show',
                    'start', 'stop', 'remove', 'delete', 'install', 'refactor', 'implement',
                    'make', 'change', 'write', 'check', 'debug', 'test', 'push', 'pull',
                    'resume', 'continue', 'revert', 'reset', 'send', 'open', 'close'}
_GATEWAY_QA_URL = 'http://localhost:18789/ask'
_GATEWAY_QA_PROJECT = 'qa'


def _is_simple_question(text: str) -> bool:
    """Return True if this is a general-knowledge question that can bypass the full router.

    Conservative: only matches when there's no known-project mention and no action verb.
    """
    t = text.strip()
    if not t or len(t) > 500:
        return False
    words_lower = re.findall(r'\b\w+\b', t.lower())
    if not words_lower:
        return False
    first = words_lower[0]
    # Reject if starts with an action verb
    if first in _ACTION_STARTERS:
        return False
    # Reject if mentions a known project slug
    _refresh_projects()
    if any(name in words_lower for name in _known_projects):
        return False
    # Accept if clearly a question
    return t.endswith('?') or first in _QA_STARTERS


async def _gateway_ask(message: str) -> str | None:
    """Call /ask with context=none. Returns response text or None on error."""
    import urllib.request
    import urllib.error

    def _call() -> str | None:
        body = json.dumps({
            'project': _GATEWAY_QA_PROJECT,
            'message': message,
            'context': 'none',
        }).encode('utf-8')
        req = urllib.request.Request(
            _GATEWAY_QA_URL, data=body,
            headers={'Authorization': f'Bearer {_gateway_token}',
                     'Content-Type': 'application/json'},
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read())
                return data.get('response')
        except urllib.error.HTTPError as e:
            log.warning('gateway /ask HTTP %d for Q&A', e.code)
            return None
        except Exception as e:
            log.warning('gateway /ask error: %s', e)
            return None

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

RESTART_SIGNAL_FILE = LOGDIR / 'restart-bot.signal'


async def watch_restart_signal():
    """Exit cleanly when restart-bot.py drops a signal file. NSSM auto-restarts the app."""
    while True:
        await asyncio.sleep(2)
        if RESTART_SIGNAL_FILE.exists():
            try:
                RESTART_SIGNAL_FILE.unlink()
            except Exception:
                pass
            _tl({'ts': _ts_iso(), 'event': 'restart_signal_received'})
            _log_human('Restart signal received — exiting for NSSM restart')
            log.info('restart signal received — exiting for NSSM restart')
            os._exit(0)


@client.event
async def on_ready():
    log.info('ready user=%s id=%s', client.user, client.user.id)
    _tl({'ts': _ts_iso(), 'event': 'bot_ready', 'user': str(client.user), 'user_id': client.user.id})
    _log_human(f'Bot ready: {client.user} (id={client.user.id})')
    asyncio.create_task(watch_claude_sessions())
    asyncio.create_task(watch_restart_signal())
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

    # --- Q&A fast path: simple questions bypass the full router ---
    if _gateway_token and _is_simple_question(content):
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'qa_fast_path_attempt',
             'msg_len': len(content), 'content_preview': content[:100]})
        _log_human(f'[{sid}] Q&A fast path: routing to gateway')
        resp = await _gateway_ask(content)
        if resp:
            watermarked = resp.strip() + '\n-# sent by claude'
            try:
                await message.reply(watermarked)
            except Exception as e:
                log.warning('[%s] qa fast-path reply failed: %s', sid, e)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'qa_fast_path_done',
                 'response_len': len(resp), 'elapsed_ms': elapsed_ms})
            _log_human(f'[{sid}] Q&A fast path done: {elapsed_ms}ms, {len(resp)}ch')
            return
        # Gateway failed — fall through to normal delegate dispatch
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'qa_fast_path_fallback',
             'reason': 'gateway returned no response'})
        _log_human(f'[{sid}] Q&A fast path fallback: gateway failed, using router')

    # --- Project slug matching + per-project concurrency ---
    slug = _match_project(content)

    # Check if this slug already has a running delegate
    if slug in _running_delegates:
        old_pid = _running_delegates[slug]
        if _is_pid_alive(old_pid):
            _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'delegate_busy',
                 'slug': slug, 'existing_pid': old_pid})
            _log_human(f'[{sid}] Slug {slug} busy (pid={old_pid})')
            log.info('[%s] slug=%s busy pid=%d', sid, slug, old_pid)
            await message.reply(f'Still working on `{slug}` \u2014 please resend in a moment.')
            return
        else:
            # Stale PID, clean up
            del _running_delegates[slug]

    log.info('[%s] dispatch channel=%s slug=%s msg_len=%d attachments=%d', sid, message.channel.id, slug, len(content), attach_count)

    try:
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
