#!/usr/bin/env python3
"""
Unit tests for bin/rc_commands.py (OC-041): Discord `rc` command parsing + formatting.
Pure functions; no Discord, no claude CLI.
"""
import io
import sys
import time
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PASS = 0
FAIL = 0
sys.path.insert(0, str(Path(__file__).parent.parent / 'bin'))

import rc_commands as rcc  # noqa: E402


def p(msg):
    global PASS; PASS += 1
    print(f'  PASS: {msg}')


def f(msg):
    global FAIL; FAIL += 1
    print(f'  FAIL: {msg}')


def check(cond, msg):
    p(msg) if cond else f(msg)


KNOWN = {'dairy': 'C:/p/dairy', 'dairy_llm_gateway': 'C:/p/dairy_llm_gateway',
         'shaadibot': 'C:/p/shaadibot', 'cricketapp': 'C:/p/cricketApp'}
PENDING_CONVO = {'kind': 'convo', 'expires': time.time() + 60, 'path': 'C:/p/dairy', 'convos': ['a', 'b']}
PENDING_ELSEWHERE = {'kind': 'elsewhere', 'expires': time.time() + 60, 'path': 'C:/p/dairy', 'session_id': 'a'}
PENDING_EXPIRED = {'kind': 'convo', 'expires': time.time() - 1, 'path': 'C:/p/dairy', 'convos': ['a']}

print('\n--- parse: not ours (falls through to normal routing) ---')
check(rcc.parse('rc car won\u2019t charge', KNOWN) is None, 'rc + unknown word + text -> None')
check(rcc.parse('rc car', KNOWN) is None, 'rc + unknown word -> None')
check(rcc.parse('fix the dairy app', KNOWN) is None, 'normal message -> None')
check(rcc.parse('rcdairy', KNOWN) is None, 'no space after rc -> None')
check(rcc.parse('rc dairy please fix the login', KNOWN) is None, 'project + free text -> None')
check(rcc.parse('3', KNOWN, None) is None, 'bare number without pending -> None')
check(rcc.parse('3', KNOWN, PENDING_EXPIRED) is None, 'bare number with expired pending -> None')
check(rcc.parse('copy', KNOWN, PENDING_CONVO) is None, 'copy when not asked -> None')

print('\n--- parse: commands ---')
check(rcc.parse('rc', KNOWN) == {'action': 'help'}, 'rc -> help')
check(rcc.parse('RC help', KNOWN) == {'action': 'help'}, 'RC help -> help (case-insensitive)')
check(rcc.parse('rc list', KNOWN) == {'action': 'list'}, 'rc list')
check(rcc.parse('rc restore', KNOWN) == {'action': 'restore'}, 'rc restore')
check(rcc.parse('rc create myapp', KNOWN) == {'action': 'create', 'name': 'myapp'}, 'rc create myapp')
check(rcc.parse('rc new myapp', KNOWN) == {'action': 'create', 'name': 'myapp'}, 'rc new myapp -> create')
check(rcc.parse('rc create my&app', KNOWN)['action'] == 'bad_name', 'shell metachar name rejected')
check(rcc.parse('rc create ..', KNOWN)['action'] == 'bad_name', 'dot-dot name rejected')
check(rcc.parse('rc dairy', KNOWN)['path'] == 'C:/p/dairy', 'rc dairy -> exact project path')
check(rcc.parse('rc dairy', KNOWN)['arg'] is None, 'rc dairy -> no arg')
check(rcc.parse('rc Dairy new', KNOWN)['arg'] == 'new', 'rc Dairy new -> arg new')
check(rcc.parse('rc dairy 2', KNOWN)['arg'] == '2', 'rc dairy 2 -> arg 2')
check(rcc.parse('rc dair', KNOWN)['candidates'] == ['dairy', 'dairy_llm_gateway'], 'partial -> candidates')
check(rcc.parse('rc dair', KNOWN)['path'] is None, 'partial -> no path')
check(rcc.parse('rc stop shaadibot', KNOWN)['path'] == 'C:/p/shaadibot', 'rc stop project')
check(rcc.parse('rc stop zzz', KNOWN)['candidates'] == [], 'rc stop unknown -> empty candidates')

print('\n--- parse: pending answers ---')
check(rcc.parse('2', KNOWN, PENDING_CONVO) == {'action': 'pick', 'n': 2}, 'number answers pending list')
check(rcc.parse(' 0 ', KNOWN, PENDING_CONVO) == {'action': 'pick', 'n': 0}, '0 = new conversation')
check(rcc.parse('copy', KNOWN, PENDING_ELSEWHERE) == {'action': 'copy'}, 'copy answers elsewhere')
check(rcc.parse('Takeover', KNOWN, PENDING_ELSEWHERE) == {'action': 'takeover'}, 'takeover answers elsewhere')
check(rcc.parse('rc list', KNOWN, PENDING_CONVO) == {'action': 'list'}, 'commands still work while pending')

print('\n--- format ---')
convos = [
    {'session_id': 'a', 'mtime': 1790739806, 'title': 'Shaadi interface update', 'first_prompt': 'ok the',
     'user_turns': 18, 'source': 'terminal'},
    {'session_id': 'b', 'mtime': 1790737094, 'title': '', 'first_prompt': 'deploy the apk',
     'user_turns': 3, 'source': 'discord'},
]
txt = rcc.format_conversations('shaadibot', convos, {'a'}, set())
check('**1.** \U0001f5a5' in txt, 'terminal icon on item 1')
check('Shaadi interface update \u00b7 18 msgs \u00b7 \U0001f7e2 live on RC' in txt, 'live RC marker')
check('**2.** \U0001f4ac' in txt and 'deploy the apk' in txt, 'discord item falls back to first prompt')
check('**0.** \u2795 new conversation' in txt, 'option 0 = new')
txt = rcc.format_conversations('shaadibot', convos, set(), {'b'})
check('\U0001f512 open in a terminal' in txt, 'open-in-terminal marker')
check(len(txt) < 2000, 'fits in one Discord message')
check('`takeover` \u2014 close' in rcc.format_live_elsewhere('dairy', 'idle'), 'idle offers takeover')
check('busy now' in rcc.format_live_elsewhere('dairy', 'busy'), 'busy explains takeover unavailable')
check('**2.** `D:\\x`' in rcc.format_roots('myapp', ['C:\\p', 'D:\\x']), 'roots numbered from 1')
ready = rcc.format_ready({'name': 'dairy', 'url': 'https://claude.ai/code/session_X', 'job_id': 'abcd1234'})
check('https://claude.ai/code/session_X' in ready, 'ready message has link')
check('copy' in rcc.format_ready({'name': 'd', 'url': 'u', 'job_id': 'j', 'copied': True}), 'copy noted')
check('already live' in rcc.format_ready({'name': 'd', 'url': 'u', 'job_id': 'j', 'reused': True}), 'reuse noted')
check('rc stop dairy' in rcc.format_guard('dairy', 'u'), 'guard explains how to stop')
check('Nothing to restore' in rcc.format_restore([]), 'empty restore')

print('=' * 50)
print(f'Results: {PASS} passed, {FAIL} failed')
sys.exit(0 if FAIL == 0 else 1)
