#!/usr/bin/env python3
"""discord-send.py — post or edit a message in a Discord channel via REST API.

Usage: python discord-send.py --target CHANNEL_ID --message "text"
       python discord-send.py --target CHANNEL_ID --message "text" --edit MESSAGE_ID
"""
import argparse
import io
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

CONFIG_PATH = Path.home() / '.openclaw' / 'openclaw.json'


def main():
    parser = argparse.ArgumentParser(description='Send a message to Discord')
    parser.add_argument('--channel', default=None)  # legacy compat, ignored
    parser.add_argument('--target', required=True, help='Discord channel ID')
    parser.add_argument('--message', required=True, help='Message to send')
    parser.add_argument('--edit', metavar='MESSAGE_ID', default=None,
                        help='Edit existing message (PATCH instead of POST)')
    args = parser.parse_args()

    try:
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        token = config['channels']['discord']['token']
    except Exception as e:
        print(f'discord-send: failed to read token: {e}', file=sys.stderr)
        sys.exit(1)

    if not token:
        print('discord-send: token is empty', file=sys.stderr)
        sys.exit(1)

    body = json.dumps({'content': args.message}).encode('utf-8')
    url = f'https://discord.com/api/v10/channels/{args.target}/messages'
    if args.edit:
        url += f'/{args.edit}'
    method = 'PATCH' if args.edit else 'POST'
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            'Authorization': f'Bot {token}',
            'Content-Type': 'application/json',
            'User-Agent': 'DiscordBot (https://github.com/pranavhj/openclaw-config, 1.0)',
        },
        method=method,
    )

    try:
        with urllib.request.urlopen(req) as resp:
            resp_body = resp.read()
            if resp.status == 200:
                data = json.loads(resp_body)
                msg_id = data.get('id', '')
                if msg_id:
                    print(f'MSG_ID:{msg_id}')
                if not args.edit:
                    print('\u2705 Sent via Discord REST')
                    # Test-mode capture: append message to file if env var set
                    capture_file = os.environ.get('OPENCLAW_TEST_CAPTURE_FILE')
                    if capture_file:
                        with open(capture_file, 'a', encoding='utf-8') as cf:
                            cf.write(args.message + '\n---MSG_SEP---\n')
            else:
                print(f'discord-send: HTTP {resp.status}', file=sys.stderr)
                sys.exit(1)
    except urllib.error.HTTPError as e:
        print(f'discord-send: HTTP {e.code}', file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f'discord-send: connection error: {e.reason}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
