#!/usr/bin/env python3
"""discord-send.py — post or edit a message in a Discord channel via REST API.

Usage: python discord-send.py --target CHANNEL_ID --message "text"
       python discord-send.py --target CHANNEL_ID --message "text" --edit MESSAGE_ID
       python discord-send.py --target CHANNEL_ID --message "text" --image /path/to/screenshot.png
"""
import argparse
import io
import json
import mimetypes
import os
import sys
import time
import urllib.request
import urllib.error
import uuid
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
    parser.add_argument('--image', default=None,
                        help='Path to image file to attach')
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

    # Split long messages into chunks (Discord limit: 2000 chars)
    MAX_LEN = 2000
    message = args.message
    if args.edit or len(message) <= MAX_LEN:
        chunks = [message]
    else:
        # Split on newlines near the limit, preserving readability
        chunks = []
        while len(message) > MAX_LEN:
            split_at = message.rfind('\n', 0, MAX_LEN)
            if split_at <= 0:
                split_at = MAX_LEN
            chunks.append(message[:split_at])
            message = message[split_at:].lstrip('\n')
        if message:
            chunks.append(message)

    # Validate image if provided
    image_path = None
    if args.image:
        image_path = Path(args.image)
        if not image_path.is_file():
            print(f'discord-send: image not found: {args.image}', file=sys.stderr)
            sys.exit(1)

    base_url = f'https://discord.com/api/v10/channels/{args.target}/messages'
    base_headers = {
        'Authorization': f'Bot {token}',
        'User-Agent': 'DiscordBot (https://github.com/pranavhj/openclaw-config, 1.0)',
    }

    def _send_json(content, edit_id=None):
        """Send a text-only message (JSON body)."""
        url = base_url + (f'/{edit_id}' if edit_id else '')
        method = 'PATCH' if edit_id else 'POST'
        body = json.dumps({'content': content}).encode('utf-8')
        headers = {**base_headers, 'Content-Type': 'application/json'}
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        return _do_request(req)

    def _send_multipart(content, img_path):
        """Send a message with an image attachment (multipart/form-data)."""
        boundary = uuid.uuid4().hex
        filename = img_path.name
        mime_type = mimetypes.guess_type(str(img_path))[0] or 'application/octet-stream'

        parts = []
        # Part 1: payload_json
        parts.append(
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="payload_json"\r\n'
            f'Content-Type: application/json\r\n\r\n'
            f'{json.dumps({"content": content})}\r\n'
        )
        # Part 2: file
        parts.append(
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="files[0]"; filename="{filename}"\r\n'
            f'Content-Type: {mime_type}\r\n\r\n'
        )
        file_data = img_path.read_bytes()
        closing = f'\r\n--{boundary}--\r\n'

        body = b''.join([
            parts[0].encode('utf-8'),
            parts[1].encode('utf-8'),
            file_data,
            closing.encode('utf-8'),
        ])

        headers = {**base_headers, 'Content-Type': f'multipart/form-data; boundary={boundary}'}
        req = urllib.request.Request(base_url, data=body, headers=headers, method='POST')
        return _do_request(req)

    def _do_request(req):
        """Execute HTTP request, return message ID or exit on error. Retries on transient failures."""
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                with urllib.request.urlopen(req) as resp:
                    resp_body = resp.read()
                    if resp.status == 200:
                        data = json.loads(resp_body)
                        return data.get('id', '')
                    else:
                        print(f'discord-send: HTTP {resp.status}', file=sys.stderr)
                        sys.exit(1)
            except urllib.error.HTTPError as e:
                # Retry on 5xx (server errors) and 429 (rate limit)
                if e.code in (429, 500, 502, 503, 504) and attempt < max_attempts:
                    wait = 2 ** attempt  # 2s, 4s
                    print(f'discord-send: HTTP {e.code}, retrying in {wait}s (attempt {attempt}/{max_attempts})', file=sys.stderr)
                    time.sleep(wait)
                    continue
                print(f'discord-send: HTTP {e.code}', file=sys.stderr)
                sys.exit(1)
            except urllib.error.URLError as e:
                if attempt < max_attempts:
                    wait = 2 ** attempt
                    print(f'discord-send: connection error: {e.reason}, retrying in {wait}s (attempt {attempt}/{max_attempts})', file=sys.stderr)
                    time.sleep(wait)
                    continue
                print(f'discord-send: connection error: {e.reason}', file=sys.stderr)
                sys.exit(1)

    last_msg_id = None

    if image_path:
        # Image mode: send all text + image in one message (no chunking for image messages)
        msg_id = _send_multipart(args.message[:MAX_LEN], image_path)
        if msg_id:
            last_msg_id = msg_id
    else:
        for i, chunk in enumerate(chunks):
            msg_id = _send_json(chunk, edit_id=args.edit if args.edit else None)
            if msg_id:
                last_msg_id = msg_id

    if last_msg_id:
        print(f'MSG_ID:{last_msg_id}')
    if not args.edit:
        if len(chunks) > 1:
            print(f'\u2705 Sent via Discord REST ({len(chunks)} messages)')
        else:
            print('\u2705 Sent via Discord REST')
        # Test-mode capture: append message to file if env var set
        capture_file = os.environ.get('OPENCLAW_TEST_CAPTURE_FILE')
        if capture_file:
            with open(capture_file, 'a', encoding='utf-8') as cf:
                cf.write(args.message + '\n---MSG_SEP---\n')


if __name__ == '__main__':
    main()
