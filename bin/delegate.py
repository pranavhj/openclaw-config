#!/usr/bin/env python3
"""delegate.py — orchestrate a Discord message through the Claude pipeline.

Usage: python delegate.py CHANNEL TARGET MESSAGE...
  CHANNEL  — channel type (e.g. 'discord')
  TARGET   — Discord channel ID to reply to
  MESSAGE  — message text (remaining args joined with spaces)
"""
import glob
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
STOP_SIGNAL_FILE = LOGDIR / 'stop.signal'
WORK_DIR = Path.home() / 'projects' / 'openclaw'
CLAUDE_PROJECTS_DIR = os.path.expanduser('~/.claude/projects')


def ts_ms() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime('%Y-%m-%dT%H:%M:%S.') + f'{now.microsecond // 1000:03d}Z'


TRIVIAL_REPLIES = {'SENT', 'Output: SENT', 'done', 'Done', 'OK', 'ok'}


def _extract_reply_from_jsonl(path, max_chars=500) -> str:
    """Extract the last meaningful assistant text from a JSONL file."""
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as f:
            if size > 20480:
                f.seek(size - 20480)
            data = f.read().decode('utf-8', errors='replace')
        lines = data.splitlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                msg = entry.get('message', {})
                if msg.get('role') != 'assistant':
                    continue
                content = msg.get('content', [])
                text = ''
                if isinstance(content, str):
                    text = content.strip()
                elif isinstance(content, list):
                    parts = []
                    for c in content:
                        if isinstance(c, dict) and c.get('type') == 'text':
                            t = c.get('text', '').strip()
                            if t:
                                parts.append(t)
                    text = ' '.join(parts)
                # Skip trivial marker strings
                if text and text not in TRIVIAL_REPLIES:
                    return text[:max_chars]
            except (json.JSONDecodeError, AttributeError):
                continue
    except Exception:
        pass
    return ''


def _extract_last_reply(agent_start_time=None, max_chars=500) -> str:
    """Find JONSLs modified during the agent run and extract the last meaningful assistant text.

    Checks most recently modified files first. Skips trivial replies like 'SENT'.
    If agent_start_time (time.time() epoch) is given, only considers files modified after that.
    """
    try:
        jsonl_files = glob.glob(f'{CLAUDE_PROJECTS_DIR}/**/*.jsonl', recursive=True)
        if not jsonl_files:
            return ''
        # Filter to files modified after agent started (if given)
        if agent_start_time:
            jsonl_files = [f for f in jsonl_files if os.path.getmtime(f) >= agent_start_time]
        if not jsonl_files:
            return ''
        # Sort by mtime descending — check newest files first
        jsonl_files.sort(key=os.path.getmtime, reverse=True)
        for path in jsonl_files[:5]:  # check up to 5 most recent
            reply = _extract_reply_from_jsonl(path, max_chars)
            if reply:
                return reply
    except Exception:
        pass
    return ''


def discord_send(channel: str, target: str, message: str) -> int:
    result = subprocess.run(
        [sys.executable, str(DISCORD_SEND_PY),
         '--channel', channel, '--target', target, '--message', message],
        capture_output=True, text=True,
    )
    return result.returncode


def parse_history(log_lines: list) -> str:
    """Parse timeline JSONL lines and return formatted last 5 request+reply pairs."""
    entries = []  # list of (proj, user_msg, reply_preview)
    i = 0
    while i < len(log_lines):
        try:
            e = json.loads(log_lines[i].strip())
            if e.get('event') == 'delegate_recv':
                msg = e.get('msg_preview', '')[:300]
                proj = 'openclaw'
                reply = ''
                for j in range(i + 1, min(i + 20, len(log_lines))):
                    try:
                        n = json.loads(log_lines[j].strip())
                        if n.get('event') == 'project_match':
                            proj = n.get('project', 'openclaw')
                        elif n.get('event') == 'delegate_reply':
                            reply = n.get('reply_preview', '')
                        elif n.get('event') == 'delegate_recv':
                            break  # next request, stop scanning
                    except Exception:
                        pass
                entries.append((proj, msg, reply))
        except Exception:
            pass
        i += 1
    recent = entries[-5:-1] if len(entries) >= 2 else entries[:-1]
    lines = []
    for proj, msg, reply in recent:
        lines.append(f'- [{proj}] User: {msg}')
        if reply:
            lines.append(f'  Claude: {reply}')
    return '\n'.join(lines)


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

    _was_cancelled = False
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

        _was_cancelled = _run(channel, target, message, today, log_file, tl_log, ts_recv, orig_len, sanitized_len, t0, tl, log)
    finally:
        # Edit status message to "Done" or "Cancelled" before cleanup
        if status_msg_id:
            try:
                elapsed_s = int(time.monotonic() - t0)
                if _was_cancelled:
                    msg = f'\u274c Cancelled \u00b7 {elapsed_s}s'
                else:
                    msg = f'\u2705 Done \u00b7 {elapsed_s}s'
                subprocess.run(
                    [sys.executable, str(DISCORD_SEND_PY), '--target', target,
                     '--message', msg,
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
    """Run the agent pipeline. Returns True if execution was cancelled via stop signal."""

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
    # Note: openclaw-config removed from exclusion — user works on this infra via Discord
    EXCLUDE_NAMES: set = set()

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
    t_agent_wall = time.time()  # wall-clock for JSONL file mtime filtering
    tl({'ts': ts_agent_start, 'event': 'agent_start', 'channel': channel, 'target': target})

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    agent_env = {k: v for k, v in os.environ.items() if k != 'CLAUDECODE'}

    # Write prompt to a temp file — avoids cmd.exe newline-splitting when
    # passing multi-line strings via shell=True on Windows.
    prompt_file = LOGDIR / f'delegate-prompt-{ts_recv.replace(":", "-").replace(".", "-")}.txt'
    prompt_file.write_text(prompt, encoding='utf-8')

    # Clean up any stale stop signal from previous run
    try:
        STOP_SIGNAL_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    was_stopped = False
    try:
        proc = subprocess.Popen(
            [sys.executable, str(AGENT_SMART_PY),
             '--continue',
             '--permission-mode', 'bypassPermissions',
             '--max-turns', '40',
             '--model', 'haiku', '--print-file', str(prompt_file)],
            cwd=str(WORK_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=agent_env,
        )

        # Poll for stop signal while process runs
        while proc.poll() is None:
            if STOP_SIGNAL_FILE.exists():
                ts_stop = ts_ms()
                tl({'ts': ts_stop, 'event': 'stop_signal_detected'})
                log('stop signal detected — terminating agent')
                was_stopped = True
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                break
            time.sleep(0.5)

        stdout, stderr = proc.communicate(timeout=5)
        exit_code = proc.returncode
        output = (stdout or '') + (stderr or '')
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        exit_code = proc.returncode
        output = (stdout or '') + (stderr or '') + '\n[timeout]'
    except Exception as e:
        output = f'[error spawning agent: {e}]'
        exit_code = 1
    finally:
        try:
            prompt_file.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            STOP_SIGNAL_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    duration_ms = int((time.monotonic() - t_agent) * 1000)
    ts_agent_done = ts_ms()

    log(f'--- agent output ---\n{output[:2000]}')
    tl({'ts': ts_agent_done, 'event': 'agent_done', 'exit_code': exit_code,
        'duration_ms': duration_ms, 'output_preview': output[:60].replace('\n', ' ')})

    # Extract and log Claude's reply from the JSONL session file
    reply_preview = _extract_last_reply(agent_start_time=t_agent_wall, max_chars=300)
    if reply_preview:
        tl({'ts': ts_ms(), 'event': 'delegate_reply',
            'reply_preview': reply_preview.replace('\n', ' ')})

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

    # --- Fallback: forward stdout to Discord if Claude replied directly ---
    # Sometimes Claude (especially with --continue) prints the response to stdout
    # instead of using discord-send.py. Forward it so the user sees the full reply.
    output_stripped = output.strip()
    if exit_code == 0 and 'SENT' not in output and output_stripped and output_stripped not in ('', 'SENT'):
        # Filter out agent-smart noise lines
        reply_lines = [l for l in output_stripped.splitlines()
                       if not l.startswith('[agent-smart]')]
        reply_text = '\n'.join(reply_lines).strip()
        if reply_text:
            tl({'ts': ts_ms(), 'event': 'stdout_forward',
                'chars': len(reply_text)})
            discord_send(channel, target, reply_text + '\n-# sent by delegate (stdout)')
            output = 'SENT'

    # --- Failure handling ---
    if exit_code != 0 and 'SENT' not in output:
        ts_fail = ts_ms()
        tl({'ts': ts_fail, 'event': 'failure_detected', 'exit_code': exit_code,
            'output_preview': output[:100].replace('\n', ' ')})
        # Don't send error message if we stopped intentionally
        if exit_code == 124:  # Timeout exit code
            tl({'ts': ts_fail, 'event': 'timeout_detected', 'limit_seconds': 1200})
            discord_send(channel, target,
                         'Session timed out (20min limit). Please send your request again.\n-# sent by delegate')
        elif not (exit_code == -15 or exit_code == 143):  # SIGTERM exit codes
            discord_send(channel, target,
                         f'Delegation failed (exit {exit_code}). Please try again.\n-# sent by delegate')
        else:
            discord_send(channel, target,
                         'Execution stopped.\n-# sent by delegate')
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
    return was_stopped


if __name__ == '__main__':
    main()
