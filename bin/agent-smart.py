#!/usr/bin/env python3
"""agent-smart.py — wrapper around `claude --continue` that auto-compacts large sessions.

When the most recent session file exceeds THRESHOLD_KB, creates a new session
keeping the last KEEP_PAIRS user/assistant exchanges as context.

Usage: python agent-smart.py [claude args...]

NOTE: Session directory naming on Windows must be verified.
  Claude Code derives the session dir key from the CWD path.
  On Windows: C:\\Users\\prana\\projects\\openclaw -> C--Users-prana-projects-openclaw
  Run `claude --continue` once in ~/projects/openclaw to confirm the dir name
  created under ~/.claude/projects/ and adjust get_cwd_key() if needed.

NOTE: On Windows, claude is typically installed as a .cmd file (via npm).
  shell=True is used to invoke it through cmd.exe. This means that any %var%
  patterns in --print arguments may be expanded by cmd.exe; this is acceptable
  for normal message content.
"""
import json
import subprocess
import sys
import uuid
from pathlib import Path

THRESHOLD_KB = 400
KEEP_PAIRS = 5


def get_cwd_key() -> str:
    """Derive Claude Code's session directory key from the current working directory.

    Mirrors the Linux behavior: `pwd | sed 's|/|-|g'`
    On Windows paths like C:\\Users\\prana\\projects\\openclaw the result is
    C--Users-prana-projects-openclaw.
    """
    cwd = str(Path.cwd())
    return cwd.replace('\\', '-').replace('/', '-').replace(':', '-')


def maybe_compact(session_dir: Path) -> None:
    """Compact the current session file if it exceeds the size threshold."""
    if not session_dir.is_dir():
        return

    jsonl_files = list(session_dir.glob('*.jsonl'))
    if not jsonl_files:
        return

    current = max(jsonl_files, key=lambda p: p.stat().st_mtime)
    size_kb = current.stat().st_size // 1024
    if size_kb <= THRESHOLD_KB:
        return

    print(f'[agent-smart] session {size_kb}KB > {THRESHOLD_KB}KB — compacting, keeping last {KEEP_PAIRS} pairs')

    try:
        lines = current.read_text(encoding='utf-8', errors='replace').splitlines(keepends=True)
        msg_entries = []
        for line in lines:
            try:
                if json.loads(line.strip()).get('type') in ('user', 'assistant'):
                    msg_entries.append(line)
            except Exception:
                pass
        keep_n = KEEP_PAIRS * 2
        kept = msg_entries[-keep_n:]

        dst = session_dir / f'{uuid.uuid4()}.jsonl'
        dst.write_text(''.join(kept), encoding='utf-8')
        current.unlink()
        print(f'[agent-smart] {len(lines)} lines -> {len(kept)} lines ({dst.stat().st_size} bytes)')
    except Exception as e:
        print(f'[agent-smart] compaction error: {e}', file=sys.stderr)


def main():
    cwd_key = get_cwd_key()
    session_dir = Path.home() / '.claude' / 'projects' / cwd_key
    maybe_compact(session_dir)

    # On Windows, claude is a .cmd file that requires cmd.exe to execute.
    # shell=True lets Python invoke it through cmd.exe automatically.
    shell = sys.platform == 'win32'
    result = subprocess.run(['claude'] + sys.argv[1:], shell=shell)
    sys.exit(result.returncode)


if __name__ == '__main__':
    main()
