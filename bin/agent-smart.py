#!/usr/bin/env python3
"""agent-smart.py — wrapper around `claude --continue` with session size monitoring.

Two thresholds:
  WARN_BYTES (200KB): log a notice, no action
  COMPACT_BYTES (1MB): auto-compact, keeping DEFAULT_KEEP_PAIRS user/assistant pairs

Usage:
  python agent-smart.py [--keep-pairs N] [--compact-only] [claude args...]

  --keep-pairs N    Override default pairs to keep when compacting (default: 5)
  --compact-only    Compact the session and exit without running claude
                    (used by the 'compact <project>' Discord command)

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
import re
import subprocess
import sys
import uuid
from pathlib import Path

WARN_BYTES = 200_000        # 200 KB — log a notice, no action
COMPACT_BYTES = 1_000_000   # 1 MB — auto-compact
DEFAULT_KEEP_PAIRS = 5


def get_cwd_key() -> str:
    """Derive Claude Code's session directory key from the current working directory.

    Claude Code converts all non-alphanumeric characters to dashes.
    e.g. C:\\Users\\prana\\projects\\openclaw -> C--Users-prana-projects-openclaw
         D:\\MyData\\Software\\cricket_analyzer -> D--MyData-Software-cricket-analyzer
    """
    cwd = str(Path.cwd())
    return re.sub(r'[^a-zA-Z0-9]', '-', cwd)


def compact_session(session_dir: Path, keep_pairs: int) -> None:
    """Compact the current session file, keeping the last keep_pairs user/assistant exchanges."""
    if not session_dir.is_dir():
        print(f'[agent-smart] no session dir at {session_dir}')
        return
    jsonl_files = list(session_dir.glob('*.jsonl'))
    if not jsonl_files:
        print(f'[agent-smart] no session files in {session_dir}')
        return
    current = max(jsonl_files, key=lambda p: p.stat().st_mtime)
    size_kb = current.stat().st_size // 1024
    print(f'[agent-smart] compacting session ({size_kb}KB) — keeping last {keep_pairs} pairs')
    try:
        lines = current.read_text(encoding='utf-8', errors='replace').splitlines(keepends=True)
        msg_entries = []
        for line in lines:
            try:
                if json.loads(line.strip()).get('type') in ('user', 'assistant'):
                    msg_entries.append(line)
            except Exception:
                pass
        keep_n = keep_pairs * 2
        kept = msg_entries[-keep_n:]

        # Drop a leading user message that contains only tool_result blocks
        # (its matching tool_use was cut off by compaction).
        while kept:
            try:
                first = json.loads(kept[0].strip())
                if first.get('type') == 'user':
                    content = first.get('message', {}).get('content', [])
                    if isinstance(content, list) and content and all(
                        c.get('type') == 'tool_result' for c in content
                    ):
                        kept = kept[1:]
                        continue
            except Exception:
                pass
            break

        dst = session_dir / f'{uuid.uuid4()}.jsonl'
        dst.write_text(''.join(kept), encoding='utf-8')
        current.unlink()
        print(f'[agent-smart] {len(lines)} lines -> {len(kept)} lines ({dst.stat().st_size} bytes)')
    except Exception as e:
        print(f'[agent-smart] compaction error: {e}', file=sys.stderr)


def check_and_maybe_compact(session_dir: Path, keep_pairs: int) -> None:
    """Warn at WARN_BYTES; auto-compact at COMPACT_BYTES."""
    if not session_dir.is_dir():
        return
    jsonl_files = list(session_dir.glob('*.jsonl'))
    if not jsonl_files:
        return
    current = max(jsonl_files, key=lambda p: p.stat().st_mtime)
    size = current.stat().st_size
    if size >= COMPACT_BYTES:
        print(f'[agent-smart] session {size // 1024}KB >= {COMPACT_BYTES // 1024}KB — auto-compacting (keeping last {keep_pairs} pairs)')
        compact_session(session_dir, keep_pairs)
    elif size >= WARN_BYTES:
        print(f'[agent-smart] session {size // 1024}KB >= {WARN_BYTES // 1024}KB — approaching limit')


def main():
    # Strip our flags early — they are not claude args.
    args = list(sys.argv[1:])

    # --keep-pairs N: override default pairs to keep when compacting.
    keep_pairs = DEFAULT_KEEP_PAIRS
    if '--keep-pairs' in args:
        idx = args.index('--keep-pairs')
        keep_pairs = int(args[idx + 1])
        args = args[:idx] + args[idx + 2:]

    # --compact-only: compact and exit without running claude.
    compact_only = '--compact-only' in args
    if compact_only:
        args.remove('--compact-only')

    cwd_key = get_cwd_key()
    session_dir = Path.home() / '.claude' / 'projects' / cwd_key

    if compact_only:
        compact_session(session_dir, keep_pairs)
        return

    check_and_maybe_compact(session_dir, keep_pairs)

    # Timeout for Claude execution (default 20 minutes = 1200 seconds).
    # Can be overridden via CLAUDE_TIMEOUT environment variable.
    import os
    claude_timeout = int(os.environ.get('CLAUDE_TIMEOUT', '1200'))

    # --print-file <path>: read prompt from file and pass via --print.
    # Used by delegate.py on Windows to avoid cmd.exe newline-splitting
    # when multi-line prompts are passed as a command-line argument.
    if '--print-file' in args:
        idx = args.index('--print-file')
        prompt_file = args[idx + 1]
        args = args[:idx] + args[idx + 2:]  # remove --print-file <path>
        prompt = Path(prompt_file).read_text(encoding='utf-8')
        # Re-insert as --print with the file contents — but since shell=True
        # on Windows still has the newline problem, write it via stdin instead.
        # claude supports reading stdin when invoked with --print "-" or piped input.
        # We pass it via stdin with --print flag omitted, relying on stdin pipe.
        claude_args = ['claude'] + args
        shell = sys.platform == 'win32'
        try:
            result = subprocess.run(
                claude_args,
                input=prompt,
                text=True,
                encoding='utf-8',
                shell=shell,
                timeout=claude_timeout,
            )
            sys.exit(result.returncode)
        except subprocess.TimeoutExpired:
            print(f'[agent-smart] Claude process timeout after {claude_timeout}s — session interrupted')
            sys.exit(124)  # Standard timeout exit code

    # On Windows, cmd.exe truncates --print "value" at the first newline.
    # Intercept --print <value> and pass via stdin instead.
    if sys.platform == 'win32' and '--print' in args:
        idx = args.index('--print')
        prompt = args[idx + 1]
        args = args[:idx] + args[idx + 2:]
        try:
            result = subprocess.run(
                ['claude'] + args,
                input=prompt,
                text=True,
                encoding='utf-8',
                shell=True,
                timeout=claude_timeout,
            )
            sys.exit(result.returncode)
        except subprocess.TimeoutExpired:
            print(f'[agent-smart] Claude process timeout after {claude_timeout}s — session interrupted')
            sys.exit(124)

    # On Windows, claude is a .cmd file that requires cmd.exe to execute.
    # shell=True lets Python invoke it through cmd.exe automatically.
    shell = sys.platform == 'win32'
    try:
        result = subprocess.run(['claude'] + args, shell=shell, timeout=claude_timeout)
        sys.exit(result.returncode)
    except subprocess.TimeoutExpired:
        print(f'[agent-smart] Claude process timeout after {claude_timeout}s — session interrupted')
        sys.exit(124)


if __name__ == '__main__':
    main()
