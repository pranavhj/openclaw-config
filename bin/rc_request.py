#!/usr/bin/env python3
"""
rc_request.py — hand one `rc ...` command from the router LLM to the Discord bot (OC-043).

The router translates natural language ("open dairy so I can continue on my phone") into an
existing rc command string ("rc dairy") and calls:

    python D:\\MyData\\Software\\openclaw-config\\bin\\rc_request.py "rc dairy"

The bot (watch_rc_requests in discord-bot.py) picks the request up within ~1s, validates it
with rc_commands.parse, refuses consent actions (takeover/copy — only the user's own reply
can trigger those), runs it with the normal rc handler and replies in the channel.
The LLM never executes anything itself.

Channel defaults to $DISCORD_TARGET (set by delegate.py). Prints QUEUED <id> or ERROR <reason>.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import uuid
from pathlib import Path

LOGDIR = Path(os.getenv('LOCALAPPDATA') or tempfile.gettempdir()) / 'openclaw'
REQUEST_DIR = LOGDIR / 'rc-requests'
MAX_LEN = 200
_CMD_RE = re.compile(r'^rc(\s+\S+){0,3}$', re.IGNORECASE)


def validate(command: str) -> str | None:
    """Return an error string, or None if the command has the shape of an rc command."""
    if '\n' in command or '\r' in command:
        return 'command must be a single line'
    if len(command) > MAX_LEN:
        return f'command longer than {MAX_LEN} chars'
    if not _CMD_RE.match(command.strip()):
        return 'not an rc command (expected: rc <words>, at most 3 words after rc)'
    return None


def write_request(command: str, channel: str, request_dir: Path = REQUEST_DIR) -> str:
    request_dir.mkdir(parents=True, exist_ok=True)
    rid = f'{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}'
    data = {'id': rid, 'channel': channel, 'command': command.strip(), 'source': 'router',
            'ts': time.time()}
    tmp = request_dir / f'{rid}.tmp'
    tmp.write_text(json.dumps(data), encoding='utf-8')
    os.replace(tmp, request_dir / f'{rid}.json')  # atomic: the bot never sees a half file
    return rid


def main() -> int:
    ap = argparse.ArgumentParser(description='Queue an rc command for the Discord bot')
    ap.add_argument('command', nargs='?', help='e.g. "rc dairy" or "rc create step-counter 2"')
    ap.add_argument('--channel', default=os.environ.get('DISCORD_TARGET', ''))
    ap.add_argument('--roots', action='store_true',
                    help='print the numbered project roots used by "rc create <name> <n>" and exit')
    a = ap.parse_args()
    if a.roots:
        sys.path.insert(0, str(Path(__file__).parent))
        from project_list import FILTERED_ROOTS, UNFILTERED_ROOTS  # same order as the bot
        roots = [str(r) for r in FILTERED_ROOTS + UNFILTERED_ROOTS if r.exists()]
        for i, r in enumerate(roots, 1):
            print(f'{i}. {r}')
        return 0
    if not a.command:
        print('ERROR missing command')
        return 2
    if not a.channel:
        print('ERROR no channel (pass --channel or set DISCORD_TARGET)')
        return 2
    err = validate(a.command)
    if err:
        print(f'ERROR {err}')
        return 2
    print(f'QUEUED {write_request(a.command, a.channel)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
