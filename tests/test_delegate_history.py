#!/usr/bin/env python3
"""
Unit tests for delegate.py reply capture and history header (OC-046).

No live prerequisites: transcripts are written to a temp dir.
"""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PASS = 0
FAIL = 0
REPO_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_DIR / 'bin'))

import delegate  # noqa: E402


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  PASS: {msg}')
    else:
        FAIL += 1
        print(f'  FAIL: {msg}')


def user(text):
    return {'type': 'user', 'message': {'role': 'user', 'content': text}}


def tool_result(text):
    return {'type': 'user', 'message': {'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': 'x', 'content': text}]}}


def bash(cmd):
    return {'type': 'assistant', 'message': {'role': 'assistant', 'content': [
        {'type': 'tool_use', 'name': 'Bash', 'input': {'command': cmd}}]}}


def say(text):
    return {'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}}


def prompt(request, history=''):
    return f'## Reply\nChannel: discord\n\n## Recent messages\n{history}\n\n## Request\n{request}\n'


print('\n--- summarize_turn ---')
check(delegate.summarize_turn([
    bash('python /d/x/bin/discord-send.py --target 1 --message "Here are your projects\\n-# sent by claude"'),
    tool_result('ok'), say('SENT')]) == 'Here are your projects -# sent by claude',
    'discord-send message is what the user saw')
check(delegate.summarize_turn([bash('python /d/x/bin/rc_request.py "rc tablenew"'), tool_result('QUEUED 1'),
                               say('SENT')]) == '(submitted `rc tablenew`; the bot replied with the result)',
      'rc request recorded as the submitted command')
check(delegate.summarize_turn([bash('(cd C:/p && python D:/x/bin/agent-smart.py --continue --print "hi")'),
                               say('SENT')]) == '(handed to the project sub-session, which replied itself)',
      'sub-session spawn recorded as handed off')
check(delegate.summarize_turn([say('SENT')]) == '', 'turn with only SENT -> empty, not an older turn')
check(delegate.summarize_turn([say('Gateway is up.')]) == 'Gateway is up.', 'plain text fallback')

print('\n--- _extract_turn_reply ---')
tmp = Path(tempfile.mkdtemp(prefix='deleg-hist-'))
lines = [
    user(prompt('Remote control end effector cad')),
    bash('python /d/x/bin/rc_sessions.py convos "C:/p"'), tool_result('[]'),
    say('Nothing to resume, so the bot will start fresh.'),
    user(prompt('Start chatgpt gateway', '- [endeffectorcad] User: Remote control end effector cad')),
    bash('python /d/x/bin/rc_request.py "rc gateway chatgpt"'), tool_result('QUEUED 2'), say('SENT'),
    user(prompt('Remote control', '- User: Start chatgpt gateway')),
    say('SENT'),
]
(tmp / 'router.jsonl').write_text('\n'.join(json.dumps(x) for x in lines) + '\n', encoding='utf-8')
(tmp / 'old.jsonl').write_text(json.dumps(user(prompt('Start chatgpt gateway'))) + '\n' +
                               json.dumps(say('stale answer')) + '\n', encoding='utf-8')
os.utime(tmp / 'old.jsonl', (1000, 1000))
check(delegate._extract_turn_reply('Start chatgpt gateway', 2000, transcript_dir=tmp)
      == '(submitted `rc gateway chatgpt`; the bot replied with the result)',
      'reply comes from the turn whose Request matches, not the quoted history')
check(delegate._extract_turn_reply('Remote control end effector cad', 2000, transcript_dir=tmp)
      == 'Nothing to resume, so the bot will start fresh.', 'earlier turn found by its own Request')
check(delegate._extract_turn_reply('Remote control', 2000, transcript_dir=tmp) == '',
      'SENT-only turn does not borrow the previous turn\'s text')
check(delegate._extract_turn_reply('never sent', 2000, transcript_dir=tmp) == '', 'unknown request -> empty')
check(delegate._extract_turn_reply('Start chatgpt gateway', 9e12, transcript_dir=tmp) == '',
      'files older than the agent start are ignored')

print('\n--- history header ---')
src = (REPO_DIR / 'bin' / 'delegate.py').read_text(encoding='utf-8')
check('Only use entries matching [openclaw]' not in src, 'hardcoded [openclaw] filter removed')
check("routed to [{slug}]" in src, 'header names the project the history belongs to')

print(f'\n{"=" * 50}\nResults: {PASS} passed, {FAIL} failed')
sys.exit(1 if FAIL else 0)
