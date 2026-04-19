#!/usr/bin/env python3
"""bot-logs.py — tail the discord-bot NSSM log file (replaces `journalctl -f`).

Usage: python bot-logs.py
"""
import os
import sys
import time
from pathlib import Path

LOG_FILE = Path(os.getenv('LOCALAPPDATA') or '') / 'openclaw' / 'bot.log'


def main():
    if not LOG_FILE.exists():
        print(f'bot-logs: log file not found: {LOG_FILE}', file=sys.stderr)
        print('Is the discord-bot NSSM service running and configured to log here?', file=sys.stderr)
        sys.exit(1)

    print(f'Following {LOG_FILE} (Ctrl+C to stop)...')
    try:
        with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
            f.seek(0, 2)  # seek to end
            while True:
                line = f.readline()
                if line:
                    print(line, end='', flush=True)
                else:
                    time.sleep(0.1)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
