#!/usr/bin/env python3
"""delegate.py — orchestrate a Discord message through the Claude pipeline.

Usage: python delegate.py CHANNEL TARGET MESSAGE...
  CHANNEL  — channel type (e.g. 'discord')
  TARGET   — Discord channel ID to reply to
  MESSAGE  — message text (remaining args joined with spaces)
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

SCRIPT_DIR = Path(__file__).parent
AGENT_SMART_PY = SCRIPT_DIR / 'agent-smart.py'
DISCORD_SEND_PY = SCRIPT_DIR / 'discord-send.py'
SESSION_RESET_PY = SCRIPT_DIR / 'session-reset.py'

LOGDIR = Path(os.getenv('LOCALAPPDATA') or tempfile.gettempdir()) / 'openclaw'
ACTIVE_SESSION_FILE = LOGDIR / 'active-session.json'
WORK_DIR = Path.home() / 'projects' / 'openclaw'


def ts_ms() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime('%Y-%m-%dT%H:%M:%S.') + f'{now.microsecond // 1000:03d}Z'


def discord_send(channel: str, target: str, message: str) -> int:
    result = subprocess.run(
        [sys.executable, str(DISCORD_SEND_PY),
         '--channel', channel, '--target', target, '--message', message],
        capture_output=True, text=True,
    )
    return result.returncode


def parse_history(log_lines: list) -> str:
    """Parse timeline JSONL lines and return formatted last 5 request entries."""
    entries = []
    i = 0
    while i < len(log_lines):
        try:
            e = json.loads(log_lines[i].strip())
            if e.get('event') == 'delegate_recv':
                msg = e.get('msg_preview', '')[:300]
                proj = 'openclaw'
                for j in range(i + 1, min(i + 5, len(log_lines))):
                    try:
                        n = json.loads(log_lines[j].strip())
                        if n.get('event') == 'project_match':
                            proj = n.get('project', 'openclaw')
                            break
                    except Exception:
                        pass
                entries.append((proj, msg))
        except Exception:
            pass
        i += 1
    recent = entries[-5:-1] if len(entries) >= 2 else entries[:-1]
    return '\n'.join(f'- [{proj}] {msg}' for proj, msg in recent)


def main():
    if len(sys.argv) < 3:
        print('Usage: delegate.py CHANNEL TARGET [MESSAGE...]', file=sys.stderr)
        sys.exit(1)

    channel = sys.argv[1]
    target = sys.argv[2]
    message = ' '.join(sys.argv[3:])
    t0 = time.monotonic()

    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    LOGDIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGDIR / f'delegate-{today}.log'
    tl_log   = LOGDIR / f'timeline-{today}.log'
    lock_dir = LOGDIR / 'delegate.lock'

    ts_recv = ts_ms()

    def tl(obj: dict):
        with open(tl_log, 'a', encoding='utf-8') as f:
            f.write(json.dumps(obj) + '\n')

    def log(text: str):
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(text + '\n')

    # --- Log: delegate_recv ---
    tl({'ts': ts_recv, 'event': 'delegate_recv', 'channel': channel, 'target': target,
        'msg_len': len(message), 'msg_preview': message[:300]})

    # --- Sanitization (OC-015: apostrophes/backticks; OC-016: newlines) ---
    orig_len = len(message)
    chars_replaced = message.count("'") + message.count('`') + message.count('\n')
    message = message.replace("'", '\u2019')   # U+2019 RIGHT SINGLE QUOTATION MARK
    message = message.replace('`', '\u2018')   # U+2018 LEFT SINGLE QUOTATION MARK
    message = message.replace('\n', ' ')        # OC-016: newlines break exec
    sanitized_len = len(message)
    tl({'ts': ts_ms(), 'event': 'sanitize', 'orig_len': orig_len,
        'sanitized_len': sanitized_len, 'chars_replaced': chars_replaced})

    # --- Lock: prevent duplicate concurrent runs ---
    try:
        lock_dir.mkdir(exist_ok=False)
    except FileExistsError:
        ts_blocked = ts_ms()
        tl({'ts': ts_blocked, 'event': 'lock_blocked', 'msg': 'duplicate run detected'})
        log(f'lock_blocked: duplicate run at {ts_blocked}')
        discord_send(channel, target,
                     'Still working on a previous task \u2014 please resend in a moment.\n-# sent by delegate')
        print('SENT')
        return

    status_msg_id = None  # declared here so finally block can access it

    try:
        tl({'ts': ts_ms(), 'event': 'lock_acquired'})
        print(f'delegation started \u2014 log: {log_file}')

        # Send "Working…" status message; write active-session.json for live progress display
        try:
            send_result = subprocess.run(
                [sys.executable, str(DISCORD_SEND_PY), '--target', target,
                 '--message', '\U0001f504 Working\u2026'],
                capture_output=True, text=True,
            )
            status_msg_id = None
            for line in send_result.stdout.splitlines():
                if line.startswith('MSG_ID:'):
                    status_msg_id = line[7:].strip()
            if status_msg_id:
                ACTIVE_SESSION_FILE.write_text(json.dumps({
                    'target': target,
                    'status_message_id': status_msg_id,
                    'project': 'openclaw',
                    'ts_start': ts_recv,
                }), encoding='utf-8')
        except Exception:
            pass

        _run(channel, target, message, today, log_file, tl_log, ts_recv, orig_len, sanitized_len, t0, tl, log)
    finally:
        # Edit status message to "Done" before cleanup
        if status_msg_id:
            try:
                elapsed_s = int(time.monotonic() - t0)
                subprocess.run(
                    [sys.executable, str(DISCORD_SEND_PY), '--target', target,
                     '--message', f'\u2705 Done \u00b7 {elapsed_s}s',
                     '--edit', status_msg_id],
                    capture_output=True, text=True, timeout=5,
                )
            except Exception:
                pass
        try:
            ACTIVE_SESSION_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            lock_dir.rmdir()
        except Exception:
            pass


def _run(channel, target, message, today, log_file, tl_log, ts_recv,
         orig_len, sanitized_len, t0, tl, log):

    # --- Discover projects ---
    # Scan multiple roots; include full path so Claude can cd to the right dir.
    # Filtered roots: only dirs with .claude (active session) or PROGRESS.md (tracked).
    # Unfiltered roots: include all subdirs (user explicitly wants everything visible).
    FILTERED_ROOTS = [
        Path.home() / 'projects',
        Path.home() / 'AndroidStudioProjects',
        Path.home() / 'PycharmProjects',
        Path.home() / 'UnityProjects',
    ]
    UNFILTERED_ROOTS = [
        Path('D:/MyData/Software'),
    ]
    # Dirs to always exclude (infra/config repos, not user projects)
    EXCLUDE_NAMES = {'openclaw-config'}

    projects = []  # list of (name, full_path)
    for root in FILTERED_ROOTS:
        if not root.exists():
            continue
        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.name in EXCLUDE_NAMES:
                continue
            if (d / '.claude').exists() or (d / 'PROGRESS.md').exists():
                projects.append((d.name, str(d)))
    for root in UNFILTERED_ROOTS:
        if not root.exists():
            continue
        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.name in EXCLUDE_NAMES:
                continue
            projects.append((d.name, str(d)))
    projects_str = '\n'.join(f'{name} ({path})' for name, path in projects) if projects else 'none'

    # --- Log: human-readable header ---
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log(f'=== {now_str} ===')
    log(f'channel: {channel}')
    log(f'target: {target}')
    log(f'message: {message[:200]}')
    log(f'msg_len: {orig_len} (sanitized: {sanitized_len})')
    log(f'projects: {projects_str}')

    tl({'ts': ts_ms(), 'event': 'project_match', 'project': 'openclaw',
        'work_dir': str(WORK_DIR).replace('\\', '/')})

    # --- Recent message history (last few prior messages) ---
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d')
    yesterday_log = LOGDIR / f'timeline-{yesterday}.log'
    today_log = tl_log

    log_lines = []
    today_count = 0
    if today_log.exists():
        try:
            lines = today_log.read_text(encoding='utf-8', errors='replace').splitlines()
            today_count = sum(
                1 for l in lines
                if '"event":"delegate_recv"' in l or '"event": "delegate_recv"' in l
            )
            log_lines = lines
        except Exception:
            pass
    if today_count < 3 and yesterday_log.exists():
        try:
            prev = yesterday_log.read_text(encoding='utf-8', errors='replace').splitlines()
            log_lines = prev + log_lines
        except Exception:
            pass

    history = parse_history(log_lines)

    # --- Build prompt ---
    prompt = '## Reply\n'
    prompt += f'Channel: {channel}\nTarget: {target}\n\n'
    prompt += f'## Known projects\n{projects_str}\n\n'
    if history:
        prompt += (
            '## Recent messages (context only \u2014 do not reply to these)\n'
            f'Each entry is tagged [project]. Only use entries matching [openclaw] as context; ignore others.\n'
            f'{history}\n\n'
        )
    prompt += f'## Request\n{message}\n'

    attachments_env = os.environ.get('DELEGATE_ATTACHMENTS', '')
    if attachments_env:
        prompt += '\n## Attachments\nThe following files were uploaded with this message (use the Read tool to view them):\n'
        for path in attachments_env.split(','):
            if path.strip():
                prompt += f'{path.strip()}\n'

    tl({'ts': ts_ms(), 'event': 'prompt_ready', 'bytes': len(prompt.encode('utf-8'))})

    # --- Run agent ---
    ts_agent_start = ts_ms()
    t_agent = time.monotonic()
    tl({'ts': ts_agent_start, 'event': 'agent_start', 'channel': channel, 'target': target})

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    agent_env = {k: v for k, v in os.environ.items() if k != 'CLAUDECODE'}

    # Write prompt to a temp file — avoids cmd.exe newline-splitting when
    # passing multi-line strings via shell=True on Windows.
    prompt_file = LOGDIR / f'delegate-prompt-{ts_recv.replace(":", "-").replace(".", "-")}.txt'
    prompt_file.write_text(prompt, encoding='utf-8')
    try:
        result = subprocess.run(
            [sys.executable, str(AGENT_SMART_PY),
             '--permission-mode', 'bypassPermissions',
             '--model', 'haiku', '--print-file', str(prompt_file)],
            cwd=str(WORK_DIR),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=agent_env,
        )
    finally:
        try:
            prompt_file.unlink(missing_ok=True)
        except Exception:
            pass
    exit_code = result.returncode
    output = (result.stdout or '') + (result.stderr or '')
    duration_ms = int((time.monotonic() - t_agent) * 1000)
    ts_agent_done = ts_ms()

    log(f'--- agent output ---\n{output[:2000]}')
    tl({'ts': ts_agent_done, 'event': 'agent_done', 'exit_code': exit_code,
        'duration_ms': duration_ms, 'output_preview': output[:60].replace('\n', ' ')})

    # --- Cleanup downloaded attachments ---
    if attachments_env:
        paths = [p.strip() for p in attachments_env.split(',') if p.strip()]
        for p in paths:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass
        if paths:
            try:
                Path(paths[0]).parent.rmdir()
            except Exception:
                pass

    # --- Failure handling ---
    if exit_code != 0 and 'SENT' not in output:
        ts_fail = ts_ms()
        tl({'ts': ts_fail, 'event': 'failure_detected', 'exit_code': exit_code,
            'output_preview': output[:100].replace('\n', ' ')})
        discord_send(channel, target,
                     f'Delegation failed (exit {exit_code}). Please try again.\n-# sent by delegate')
        ts_notify = ts_ms()
        tl({'ts': ts_notify, 'event': 'failure_notified', 'notify_exit': 0})
        log(f'failure_notified at {ts_notify}')
        output = 'SENT'

    # --- Log: delegate_exit ---
    ts_exit = ts_ms()
    total_ms = int((time.monotonic() - t0) * 1000)
    tl({'ts': ts_exit, 'event': 'delegate_exit', 'total_ms': total_ms,
        'final_output': output[:40].replace('\n', ' ')})
    log(f'ts_recv: {ts_recv}')
    log(f'ts_agent_start: {ts_agent_start}')
    log(f'ts_agent_done: {ts_agent_done}')
    log(f'ts_exit: {ts_exit}')
    log(f'duration_agent_ms: {duration_ms}')
    log(f'duration_total_ms: {total_ms}')
    log(f'exit_code: {exit_code}')
    log(f'output: {output[:200]}')
    log('status: done\n')

    # --- Reset session (no-op on Windows without openclaw gateway) ---
    try:
        subprocess.run([sys.executable, str(SESSION_RESET_PY)],
                       capture_output=True, timeout=10)
    except Exception:
        pass

    print(output)


if __name__ == '__main__':
    main()
