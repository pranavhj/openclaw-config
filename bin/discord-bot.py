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

with open(os.path.expanduser('~/.openclaw/openclaw.json')) as f:
    config = json.load(f)
token = config['channels']['discord']['token']
ALLOWED_USER = 1277144623231537274

CLAUDE_PROJECTS_DIR = os.path.expanduser('~/.claude/projects')

LOGDIR = Path(os.getenv('LOCALAPPDATA') or tempfile.gettempdir()) / 'openclaw'
ACTIVE_SESSION_FILE = LOGDIR / 'active-session.json'
TOOL_ICONS = {
    'Bash': '\U0001f527', 'Edit': '\U0001f4dd', 'Read': '\U0001f4d6', 'Write': '\u270f\ufe0f',
    'Glob': '\U0001f50d', 'Grep': '\U0001f50d', 'WebFetch': '\U0001f310', 'WebSearch': '\U0001f310',
    'Task': '\U0001f916', 'TaskCreate': '\U0001f4cb', 'TaskUpdate': '\U0001f4cb',
    'TaskOutput': '\u23f3', 'Skill': '\u26a1', 'NotebookEdit': '\U0001f4d3',
    'TodoWrite': '\U0001f4cb',
}
_status_events = collections.deque(maxlen=20)
_last_edit_ts = 0.0
_active_session = None
_session_start_mono = 0.0
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

async def _edit_status(session, elapsed_s, done=False, cancelled=False):
    """Edit the in-progress status message with current tool activity."""
    channel_id = int(session['target'])
    message_id = int(session['status_message_id'])
    project = session.get('project', 'openclaw')
    if cancelled:
        header = f'\u274c Cancelled \u00b7 `{elapsed_s}s` \u00b7 {project}'
    elif done:
        header = f'\u2705 Done \u00b7 `{elapsed_s}s` \u00b7 {project}'
    else:
        header = f'\U0001f504 Working\u2026 `{elapsed_s}s` \u00b7 {project}'
    lines = [header]
    for ev in list(_status_events)[-6:]:
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
        log.warning('status edit failed: %s', e)


async def watch_claude_sessions():
    """Poll ~/.claude/projects for new JSONL lines and pretty-print to stdout."""
    global _active_session, _status_events, _last_edit_ts, _session_start_mono
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
            # Track active delegation session for live status updates
            prev_session = _active_session
            try:
                session_data = json.loads(ACTIVE_SESSION_FILE.read_text(encoding='utf-8'))
                # Max-age guard: clean up stale files (>2 hours)
                ts_start = session_data.get('ts_start', '')
                if ts_start:
                    try:
                        dt = datetime.fromisoformat(ts_start.replace('Z', '+00:00'))
                        if (datetime.now(timezone.utc) - dt).total_seconds() > 7200:
                            ACTIVE_SESSION_FILE.unlink(missing_ok=True)
                            session_data = None
                    except (ValueError, OSError):
                        pass
                if session_data is not None:
                    _active_session = session_data
                    if prev_session is None:
                        _session_start_mono = time.monotonic()
                        _status_events.clear()
                        # Re-seed all file positions so we only track new writes from this session
                        for p in glob.glob(f'{CLAUDE_PROJECTS_DIR}/**/*.jsonl', recursive=True):
                            try:
                                file_positions[p] = os.path.getsize(p)
                            except OSError:
                                pass
                elif prev_session is not None:
                    elapsed = int(time.monotonic() - _session_start_mono)
                    await _edit_status(prev_session, elapsed, done=True)
                    _active_session = None
                    _status_events.clear()
                    _last_edit_ts = 0.0
            except Exception:
                if prev_session is not None:
                    elapsed = int(time.monotonic() - _session_start_mono)
                    await _edit_status(prev_session, elapsed, done=True)
                    _active_session = None
                    _status_events.clear()
                    _last_edit_ts = 0.0

            current_files = set(glob.glob(f'{CLAUDE_PROJECTS_DIR}/**/*.jsonl', recursive=True))

            # Remove stale entries for deleted files
            for path in list(file_positions):
                if path not in current_files:
                    del file_positions[path]

            for path in current_files:
                # Skip memory files
                if '/memory/' in path:
                    continue
                try:
                    size = os.path.getsize(path)
                except OSError:
                    continue

                last = file_positions.get(path)
                if last is None:
                    # Seed at current end — only process truly new data written after this point
                    file_positions[path] = size
                    continue

                if size <= last:
                    continue

                # Read new bytes
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
                            if _active_session:
                                _active_session['project'] = project
                                if '[tool]' in msg_line:
                                    parts = msg_line.split('] [tool] ', 1)
                                    if len(parts) == 2:
                                        tool_name, _, detail = parts[1].partition(': ')
                                        _status_events.append({
                                            'type': 'tool',
                                            'tool': tool_name.strip(),
                                            'detail': detail.strip(),
                                        })
                                elif '[assistant]' in msg_line:
                                    parts = msg_line.split('] [assistant] ', 1)
                                    if len(parts) == 2:
                                        text = parts[1].strip()
                                        if text:
                                            _status_events.append({
                                                'type': 'text',
                                                'detail': text,
                                            })
                    except json.JSONDecodeError:
                        pass

            # Throttled status message edit (~every 3s)
            if _active_session and (time.monotonic() - _last_edit_ts) >= 3.0:
                elapsed = int(time.monotonic() - _session_start_mono)
                await _edit_status(_active_session, elapsed)
                _last_edit_ts = time.monotonic()

        except Exception as e:
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
            log.info('restart signal received — exiting for NSSM restart')
            os._exit(0)


@client.event
async def on_ready():
    log.info('ready user=%s id=%s', client.user, client.user.id)
    asyncio.create_task(watch_claude_sessions())
    asyncio.create_task(watch_restart_signal())
    log.info('session watcher started')

@client.event
async def on_message(message):
    if message.author.bot:
        return
    if message.author.id != ALLOWED_USER:
        log.info('ignored author=%s channel_type=%s', message.author.id, type(message.channel).__name__)
        return
    if not isinstance(message.channel, discord.DMChannel):
        log.info('ignored non-dm author=%s channel_type=%s', message.author.id, type(message.channel).__name__)
        return

    # Deduplicate: Discord gateway may deliver the same message multiple times
    if message.id in _recent_msg_ids:
        log.info('ignored duplicate message id=%s', message.id)
        return
    _recent_msg_ids.append(message.id)

    content = message.content.replace('\n', ' ')

    # Handle "stop" / "cancel" command
    if content.strip().lower() in ('stop', 'cancel'):
        try:
            stop_signal = LOGDIR / 'stop.signal'
            stop_signal.write_text('1', encoding='utf-8')
            log.info('stop signal written')
            await message.reply('\u23f9\ufe0f Cancelling\u2026')
        except Exception as e:
            log.error('stop signal failed: %s', e)
            await message.reply(f'Failed to stop: {e}')
        return

    env = None  # inherit environment; claude is already in PATH

    # Download attachments if any
    attach_count = 0
    if message.attachments:
        attach_dir = Path(tempfile.gettempdir()) / 'openclaw' / 'attachments' / str(message.id)
        attach_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for att in message.attachments:
            dest = attach_dir / att.filename
            await att.save(str(dest))
            paths.append(str(dest))
        env = {**os.environ, 'DELEGATE_ATTACHMENTS': ','.join(paths)}
        attach_count = len(paths)

    log.info('dispatch channel=%s msg_len=%d attachments=%d', message.channel.id, len(content), attach_count)

    try:
        cmd = [sys.executable, str(DELEGATE_PY), 'discord', str(message.channel.id), content]
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
        log.info('delegate pid=%d', proc.pid)
    except Exception as e:
        log.error('delegate spawn failed: %s', e)

client.run(token)
