#!/usr/bin/env python3
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
    'Glob': '\U0001f50d', 'Grep': '\U0001f50d', 'WebFetch': '\U0001f310', 'Task': '\U0001f916',
}
_status_events = []
_last_edit_ts = 0.0
_active_session = None
_session_start_mono = 0.0


def project_label(filepath):
    """Extract a short project name from a JSONL path."""
    dirname = os.path.basename(os.path.dirname(filepath))
    # e.g. -home-pranav-projects-screen-reader → screen-reader
    # Linux: -home-pranav-projects-<slug>
    for prefix in ['-home-pranav-projects-', '-home-pranav-']:
        if dirname.startswith(prefix):
            return dirname[len(prefix):]
    # Windows: C--Users-prana-projects-<slug>
    m = re.search(r'-projects-(.+)$', dirname)
    if m:
        return m.group(1)
    return dirname

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
                if isinstance(inp, dict):
                    detail = inp.get('command', inp.get('file_path', inp.get('pattern', inp.get('query', str(inp)[:120]))))
                else:
                    detail = str(inp)[:120]
                lines.append(f'[{project}] [tool] {name}: {str(detail)[:200]}')
    elif isinstance(content, str):
        text = content.replace('\n', ' ').strip()
        if text:
            lines.append(f'[{project}] [{role}] {text[:300]}')

    return lines

async def _edit_status(session, elapsed_s, done=False):
    """Edit the in-progress status message with current tool activity."""
    channel_id = int(session['target'])
    message_id = int(session['status_message_id'])
    project = session.get('project', 'openclaw')
    header = f'{"✅ Done" if done else "🔄 Working…"} `{elapsed_s}s` · {project}'
    lines = [header]
    for ev in _status_events[-5:]:
        icon = TOOL_ICONS.get(ev['tool'], '⚙️')
        lines.append(f'||{icon} **{ev["tool"]}**: {ev["detail"][:80]}||')
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
                # Max-age guard: clean up stale files (>30 min)
                ts_start = session_data.get('ts_start', '')
                if ts_start:
                    try:
                        dt = datetime.fromisoformat(ts_start.replace('Z', '+00:00'))
                        if (datetime.now(timezone.utc) - dt).total_seconds() > 1800:
                            ACTIVE_SESSION_FILE.unlink(missing_ok=True)
                            session_data = None
                    except (ValueError, OSError):
                        pass
                if session_data is not None:
                    _active_session = session_data
                    if prev_session is None:
                        _session_start_mono = time.monotonic()
                        _status_events.clear()
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
                    # New file appeared — start tracking from current end
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
                            if _active_session and '[tool]' in msg_line:
                                parts = msg_line.split('] [tool] ', 1)
                                if len(parts) == 2:
                                    tool_name, _, detail = parts[1].partition(': ')
                                    _status_events.append({
                                        'tool': tool_name.strip(),
                                        'detail': detail.strip(),
                                    })
                                    _active_session['project'] = project
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

    content = message.content.replace('\n', ' ')
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
