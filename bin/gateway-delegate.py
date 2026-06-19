#!/usr/bin/env python3
"""gateway-delegate.py — build prompt from project data + spawn Claude agent.

Stripped version of delegate.py for gateway use. No Discord integration,
no locking (gateway handles that). Returns Claude's response on stdout.
Logs to gateway-timeline-YYYY-MM-DD.log with session ID from parent.

Usage: python gateway-delegate.py [--context auto|none] [--sid ID] PROJECT_SLUG MESSAGE
"""
import argparse
import glob
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

SCRIPT_DIR = Path(__file__).parent
AGENT_SMART_PY = SCRIPT_DIR / 'agent-smart.py'
PROJECTS_ROOT = Path.home() / 'projects'
PROJECT_SUFFIX = '_llm_gateway'
CLAUDE_PROJECTS_DIR = os.path.expanduser('~/.claude/projects')
LOGDIR = Path(os.getenv('LOCALAPPDATA') or '/tmp') / 'openclaw'

# Session ID — set in main() from --sid arg
_SID = '?'


# ---------------------------------------------------------------------------
# Timeline logging (shared log file with llm-gateway.py)
# ---------------------------------------------------------------------------

def _ts_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime('%Y-%m-%dT%H:%M:%S.') + f'{now.microsecond // 1000:03d}Z'


def _tl(event: dict):
    """Append a JSONL event to the gateway timeline log."""
    try:
        today = datetime.now().strftime('%Y-%m-%d')  # local time for file date (matches delegate/discord logs)
        tl_path = LOGDIR / f'gateway-timeline-{today}.log'
        with open(tl_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(event) + '\n')
    except Exception:
        pass


def _log_stderr(msg: str):
    """Log to stderr (captured by llm-gateway.py)."""
    print(f'[delegate:{_SID}] {msg}', file=sys.stderr)


# ---------------------------------------------------------------------------
# Project helpers
# ---------------------------------------------------------------------------

def project_dir_for(slug: str) -> Path:
    return PROJECTS_ROOT / f'{slug}{PROJECT_SUFFIX}'


def load_project(slug: str) -> dict:
    """Load project.json for a project slug."""
    pj = project_dir_for(slug) / 'project.json'
    return json.loads(pj.read_text(encoding='utf-8'))


def load_instructions(slug: str) -> str:
    """Load instructions.md for a project, if it exists."""
    md = project_dir_for(slug) / 'instructions.md'
    if md.exists():
        return md.read_text(encoding='utf-8').strip()
    return ''


def load_recent_data(slug: str, days: int = 7, max_entries: int = 50) -> str:
    """Load recent JSONL entries from the project's data directory."""
    data_dir = project_dir_for(slug) / 'data'
    if not data_dir.exists():
        _tl({'ts': _ts_iso(), 'sid': _SID, 'event': 'load_data_no_dir', 'project': slug})
        return ''

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_str = cutoff.isoformat()

    total_lines = 0
    matched = 0
    entries = []
    for jsonl_file in sorted(data_dir.glob('*.jsonl')):
        try:
            for line in jsonl_file.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if not line:
                    continue
                total_lines += 1
                try:
                    entry = json.loads(line)
                    ts = entry.get('timestamp', entry.get('_ts', ''))
                    if ts >= cutoff_str:
                        entries.append(entry)
                        matched += 1
                except json.JSONDecodeError:
                    continue
        except Exception:
            continue

    entries.sort(key=lambda e: e.get('timestamp', e.get('_ts', '')), reverse=True)
    entries = entries[:max_entries]

    _tl({'ts': _ts_iso(), 'sid': _SID, 'event': 'load_data_done', 'project': slug,
         'total_lines': total_lines, 'matched': matched, 'returned': len(entries),
         'days': days, 'max_entries': max_entries})

    if not entries:
        return ''

    lines = []
    for e in reversed(entries):  # chronological order
        lines.append(json.dumps(e))
    return '\n'.join(lines)


def build_prompt(slug: str, message: str, context: str = 'auto') -> str:
    """Build the full prompt with project context + data + user message."""
    project = load_project(slug)
    parts = []

    # Project context
    display = project.get('display', slug)
    parts.append(f'## Project: {display}')

    # Instructions from instructions.md
    instructions = load_instructions(slug)
    has_instructions = bool(instructions)
    if instructions:
        parts.append(instructions)

    # Schema info
    schema = project.get('schema', {})
    if schema:
        parts.append('\n## Data Schema')
        for dtype, fields in schema.items():
            parts.append(f'### {dtype}')
            if isinstance(fields, dict):
                for field, desc in fields.items():
                    parts.append(f'- {field}: {desc}')
            else:
                parts.append(str(fields))

    # Recent data (only if context != "none")
    data_loaded = False
    if context != 'none':
        recent_data = load_recent_data(slug)
        if recent_data:
            parts.append(f'\n## Recent Data (last 7 days, max 50 entries)')
            parts.append(recent_data)
            data_loaded = True
        else:
            parts.append('\n## Recent Data\n(no entries yet)')

    # User message
    parts.append(f'\n## Request\n{message}')

    # Response instructions
    parts.append(
        '\n## Response Instructions\n'
        'Respond directly with your answer. Do NOT use any tools, do NOT call discord-send, '
        'do NOT create files. Just output your text response and nothing else. '
        'Keep your response concise and focused.'
    )

    prompt = '\n'.join(parts)

    _tl({'ts': _ts_iso(), 'sid': _SID, 'event': 'prompt_built', 'project': slug,
         'context': context, 'has_instructions': has_instructions,
         'data_loaded': data_loaded, 'schema_types': list(schema.keys()),
         'prompt_bytes': len(prompt.encode('utf-8'))})

    return prompt


def extract_response(agent_start_time: float, stdout: str, work_dir: str) -> str:
    """Extract Claude's response from stdout, with JSONL fallback scoped to work_dir."""
    # Primary: clean stdout (Claude prints response directly)
    clean_lines = [l for l in stdout.splitlines() if not l.startswith('[agent-smart]')]
    clean = '\n'.join(clean_lines).strip()
    if clean and clean not in ('SENT', 'Output: SENT', 'done', 'Done', 'OK'):
        _tl({'ts': _ts_iso(), 'sid': _SID, 'event': 'extract_from_stdout',
             'response_len': len(clean)})
        return clean

    # Fallback: extract from JSONL scoped to the delegate's session dir
    cwd_key = re.sub(r'[^a-zA-Z0-9]', '-', work_dir)
    session_dir = os.path.join(CLAUDE_PROJECTS_DIR, cwd_key)

    _tl({'ts': _ts_iso(), 'sid': _SID, 'event': 'extract_fallback_jsonl',
         'session_dir': session_dir, 'exists': os.path.isdir(session_dir),
         'stdout_was': clean[:60] if clean else '(empty)'})

    if not os.path.isdir(session_dir):
        return '(No response generated)'

    try:
        jsonl_files = [
            os.path.join(session_dir, f)
            for f in os.listdir(session_dir)
            if f.endswith('.jsonl') and os.path.getmtime(os.path.join(session_dir, f)) >= agent_start_time
        ]
        jsonl_files.sort(key=os.path.getmtime, reverse=True)

        _tl({'ts': _ts_iso(), 'sid': _SID, 'event': 'extract_jsonl_scan',
             'files_found': len(jsonl_files)})

        for path in jsonl_files[:3]:
            try:
                size = os.path.getsize(path)
                with open(path, 'rb') as f:
                    if size > 20480:
                        f.seek(size - 20480)
                    data = f.read().decode('utf-8', errors='replace')

                for line in reversed(data.splitlines()):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        msg = entry.get('message', {})
                        if msg.get('role') != 'assistant':
                            continue
                        content = msg.get('content', [])
                        if isinstance(content, str):
                            text = content.strip()
                        elif isinstance(content, list):
                            text_parts = []
                            for c in content:
                                if isinstance(c, dict) and c.get('type') == 'text':
                                    t = c.get('text', '').strip()
                                    if t:
                                        text_parts.append(t)
                            text = '\n'.join(text_parts)
                        else:
                            continue

                        if text and text not in ('SENT', 'Output: SENT', 'done', 'Done', 'OK'):
                            _tl({'ts': _ts_iso(), 'sid': _SID, 'event': 'extract_from_jsonl',
                                 'response_len': len(text), 'source': os.path.basename(path)})
                            return text
                    except (json.JSONDecodeError, AttributeError):
                        continue
            except Exception:
                continue
    except Exception:
        pass

    _tl({'ts': _ts_iso(), 'sid': _SID, 'event': 'extract_no_response'})
    return '(No response generated)'


def main():
    global _SID

    parser = argparse.ArgumentParser(description='Gateway delegate')
    parser.add_argument('--context', default='auto', choices=['auto', 'none'],
                        help='Whether to load project data into prompt')
    parser.add_argument('--sid', default='?', help='Session ID from gateway')
    parser.add_argument('slug', help='Project slug')
    parser.add_argument('message', nargs='+', help='Message text')
    args = parser.parse_args()

    _SID = args.sid
    slug = args.slug
    message = ' '.join(args.message)
    context = args.context

    _tl({'ts': _ts_iso(), 'sid': _SID, 'event': 'delegate_start',
         'project': slug, 'context': context, 'msg_len': len(message),
         'pid': os.getpid()})
    _log_stderr(f'started: project={slug} context={context} msg_len={len(message)}')

    # Validate project
    pdir = project_dir_for(slug)
    if not (pdir / 'project.json').exists():
        _tl({'ts': _ts_iso(), 'sid': _SID, 'event': 'delegate_project_not_found', 'project': slug})
        _log_stderr(f'project not found: {slug}')
        print(f'Unknown project: {slug}', file=sys.stderr)
        sys.exit(1)

    # Build prompt
    prompt = build_prompt(slug, message, context)

    # Working directory is the project's _llm_gateway dir
    work_dir = pdir
    work_dir.mkdir(parents=True, exist_ok=True)

    # Write prompt to temp file
    prompt_file = LOGDIR / f'gateway-prompt-{slug}-{_SID}-{int(time.time() * 1000)}.txt'
    LOGDIR.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(prompt, encoding='utf-8')

    _tl({'ts': _ts_iso(), 'sid': _SID, 'event': 'prompt_written',
         'path': str(prompt_file), 'bytes': len(prompt.encode('utf-8'))})

    agent_env = {k: v for k, v in os.environ.items() if k != 'CLAUDECODE'}

    t_wall = time.time()
    t_mono = time.monotonic()

    _tl({'ts': _ts_iso(), 'sid': _SID, 'event': 'agent_spawn',
         'project': slug, 'model': 'haiku', 'cwd': str(work_dir)})
    _log_stderr(f'spawning agent-smart.py (model=haiku, cwd={work_dir})')

    try:
        proc = subprocess.run(
            [sys.executable, str(AGENT_SMART_PY),
             '--continue',
             '--permission-mode', 'bypassPermissions',
             '--model', 'haiku',
             '--print-file', str(prompt_file)],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=agent_env,
            timeout=120,
        )

        agent_duration_ms = int((time.monotonic() - t_mono) * 1000)
        _tl({'ts': _ts_iso(), 'sid': _SID, 'event': 'agent_done',
             'project': slug, 'exit_code': proc.returncode,
             'duration_ms': agent_duration_ms,
             'stdout_len': len(proc.stdout), 'stderr_len': len(proc.stderr),
             'stdout_preview': proc.stdout.strip()[:120],
             'stderr_preview': proc.stderr.strip()[:120] if proc.stderr.strip() else ''})
        _log_stderr(f'agent done: exit={proc.returncode} duration={agent_duration_ms}ms stdout={len(proc.stdout)}ch')

        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            _tl({'ts': _ts_iso(), 'sid': _SID, 'event': 'agent_failed',
                 'project': slug, 'exit_code': proc.returncode, 'stderr': stderr[:500]})
            _log_stderr(f'agent FAILED: exit={proc.returncode}')
            print(f'Agent failed (exit {proc.returncode}): {stderr[:300]}', file=sys.stderr)
            sys.exit(1)

        response = extract_response(t_wall, proc.stdout, str(work_dir))

        _tl({'ts': _ts_iso(), 'sid': _SID, 'event': 'delegate_done',
             'project': slug, 'response_len': len(response),
             'total_duration_ms': int((time.monotonic() - t_mono) * 1000),
             'response_preview': response[:120]})
        _log_stderr(f'done: response={len(response)}ch')

        print(response)

    except subprocess.TimeoutExpired:
        _tl({'ts': _ts_iso(), 'sid': _SID, 'event': 'agent_timeout',
             'project': slug, 'timeout_seconds': 120})
        _log_stderr('agent TIMEOUT (120s)')
        print('Agent timed out after 120s', file=sys.stderr)
        sys.exit(124)
    except Exception as e:
        _tl({'ts': _ts_iso(), 'sid': _SID, 'event': 'delegate_exception',
             'project': slug, 'error': str(e)[:300]})
        _log_stderr(f'exception: {e}')
        raise
    finally:
        try:
            prompt_file.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == '__main__':
    main()
