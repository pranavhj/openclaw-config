#!/usr/bin/env python3
"""
test_continue_session.py — verify that --continue preserves session history
across sub-session invocations, the same way openclaw project sub-sessions work.

Creates a fresh test project, sends two messages through agent-smart.py --continue,
and checks that the second message has access to the first message's context.

Usage: python tests/test_continue_session.py [--cleanup]
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

AGENT_SMART = Path('D:/MyData/Software/openclaw-config/bin/agent-smart.py')
PROJECT_DIR = Path.home() / 'projects' / 'test-continue'
SECRET = 'DELTA-9-SIERRA'


def get_session_dir(project_dir: Path) -> Path:
    cwd_key = re.sub(r'[^a-zA-Z0-9]', '-', str(project_dir))
    return Path.home() / '.claude' / 'projects' / cwd_key


def run_message(prompt: str) -> tuple:
    """Run a single message through agent-smart.py --continue, return (exit_code, output)."""
    import os
    # Strip CLAUDECODE to allow nested invocation — same as delegate.py does
    env = {k: v for k, v in os.environ.items() if k != 'CLAUDECODE'}
    result = subprocess.run(
        [sys.executable, str(AGENT_SMART),
         '--continue',
         '--permission-mode', 'bypassPermissions',
         '--model', 'haiku',
         '--output-format', 'text',
         '--print', prompt],
        cwd=str(PROJECT_DIR),
        capture_output=True,
        text=True,
        encoding='utf-8',
        env=env,
        timeout=120,
    )
    return result.returncode, (result.stdout + result.stderr).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cleanup', action='store_true',
                        help='Remove test project and session files after test')
    args = parser.parse_args()

    session_dir = get_session_dir(PROJECT_DIR)

    print('=== test_continue_session ===')
    print(f'Project dir:  {PROJECT_DIR}')
    print(f'Session dir:  {session_dir}')
    print()

    # --- Setup: clean slate ---
    if session_dir.exists():
        removed = list(session_dir.glob('*.jsonl'))
        for f in removed:
            f.unlink()
        if removed:
            print(f'Cleared {len(removed)} prior session file(s)')

    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    (PROJECT_DIR / 'CLAUDE.md').write_text(
        '# test-continue\nYou are a test assistant. Respond concisely.',
        encoding='utf-8'
    )

    # --- Message 1: store a value ---
    print(f'[MSG 1] Asking agent to remember: {SECRET}')
    rc1, out1 = run_message(
        f'Remember this exact code: {SECRET}. Acknowledge with just the word: STORED'
    )
    print(f'  exit={rc1}  response="{out1[:120]}"')

    # Verify session file was created
    jsonl_files = list(session_dir.glob('*.jsonl')) if session_dir.exists() else []
    print(f'  Session files created: {len(jsonl_files)}')

    if not jsonl_files:
        print()
        print('FAIL: No session file found after message 1.')
        print(f'  Expected a .jsonl file in: {session_dir}')
        print('  --continue cannot work without a session file.')
        print('  Check that Claude Code is writing sessions for this CWD key.')
        return 1

    session_size = jsonl_files[0].stat().st_size
    print(f'  Session file: {jsonl_files[0].name} ({session_size} bytes)')

    # --- Message 2: recall the value ---
    print()
    print('[MSG 2] Asking agent to recall the code...')
    rc2, out2 = run_message(
        'What exact code did I ask you to remember in this session? Reply with just the code, nothing else.'
    )
    print(f'  exit={rc2}  response="{out2[:120]}"')

    # --- Result ---
    print()
    if SECRET in out2:
        print(f'PASS: --continue is working correctly.')
        print(f'  The agent recalled "{SECRET}" from the previous invocation.')
        result = 0
    else:
        print(f'FAIL: --continue not preserving session history.')
        print(f'  Expected "{SECRET}" in response, got: "{out2[:200]}"')
        print()
        print('Diagnostics:')
        print(f'  Session dir exists: {session_dir.exists()}')
        for f in session_dir.glob('*.jsonl'):
            print(f'  {f.name}: {f.stat().st_size} bytes')
        result = 1

    # --- Cleanup (optional) ---
    if args.cleanup:
        print()
        print('Cleaning up...')
        import shutil
        if PROJECT_DIR.exists():
            shutil.rmtree(PROJECT_DIR)
            print(f'  Removed {PROJECT_DIR}')
        for f in session_dir.glob('*.jsonl'):
            f.unlink()
        print(f'  Cleared session files in {session_dir}')

    return result


if __name__ == '__main__':
    sys.exit(main())
