#!/usr/bin/env python3
import discord
import subprocess
import os
import json
import logging
import asyncio
import glob

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

def project_label(filepath):
    """Extract a short project name from a JSONL path."""
    dirname = os.path.basename(os.path.dirname(filepath))
    # e.g. -home-pranav-projects-screen-reader → screen-reader
    for prefix in ['-home-pranav-projects-', '-home-pranav-']:
        if dirname.startswith(prefix):
            return dirname[len(prefix):]
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

async def watch_claude_sessions():
    """Poll ~/.claude/projects for new JSONL lines and pretty-print to stdout."""
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
                    except json.JSONDecodeError:
                        pass

        except Exception as e:
            log.error('session watcher error: %s', e)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    log.info('ready user=%s id=%s', client.user, client.user.id)
    asyncio.create_task(watch_claude_sessions())
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
    env = {**os.environ, 'PATH': '/home/pranav/.local/bin:/usr/local/bin:/usr/bin:/bin'}

    # Download attachments if any
    attach_count = 0
    if message.attachments:
        attach_dir = f'/tmp/openclaw/attachments/{message.id}'
        os.makedirs(attach_dir, exist_ok=True)
        paths = []
        for att in message.attachments:
            dest = os.path.join(attach_dir, att.filename)
            await att.save(dest)
            paths.append(dest)
        env['DELEGATE_ATTACHMENTS'] = ','.join(paths)
        attach_count = len(paths)

    log.info('dispatch channel=%s msg_len=%d attachments=%d', message.channel.id, len(content), attach_count)

    try:
        proc = subprocess.Popen(
            ['delegate', 'discord', str(message.channel.id), content],
            env=env,
            start_new_session=True
        )
        log.info('delegate pid=%d', proc.pid)
    except Exception as e:
        log.error('delegate spawn failed: %s', e)

client.run(token)
