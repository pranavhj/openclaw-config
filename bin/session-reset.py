#!/usr/bin/env python3
"""session-reset.py — clear the openclaw Gemini agent session.

This clears the legacy openclaw gateway sessions. It is a no-op if the
sessions path does not exist (e.g. on Windows where the openclaw gateway
is not installed).
"""
import json
import sys
from pathlib import Path

SESSIONS_FILE = Path.home() / '.openclaw' / 'agents' / 'main' / 'sessions' / 'sessions.json'
SESSION_KEY = 'agent:main:main'


def main():
    if not SESSIONS_FILE.exists():
        print('No active session to reset')
        return

    try:
        with open(SESSIONS_FILE) as f:
            data = json.load(f)
    except Exception as e:
        print(f'session-reset: failed to read sessions file: {e}', file=sys.stderr)
        return

    current_id = data.get(SESSION_KEY, {}).get('sessionId', '')
    if not current_id:
        print('No active session to reset')
        return

    session_file = SESSIONS_FILE.parent / f'{current_id}.jsonl'
    try:
        session_file.unlink(missing_ok=True)
    except Exception:
        pass

    data.pop(SESSION_KEY, None)
    try:
        with open(SESSIONS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        print(f'Session reset (cleared {current_id})')
    except Exception as e:
        print(f'session-reset: failed to write sessions file: {e}', file=sys.stderr)


if __name__ == '__main__':
    main()
