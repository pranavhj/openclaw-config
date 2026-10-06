#!/usr/bin/env python3
"""
Unit tests for bin/rc_request.py (OC-043): router -> bot request files.
No live prerequisites; uses a temp request dir.
"""
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PASS = 0
FAIL = 0
BIN = Path(__file__).parent.parent / 'bin'
sys.path.insert(0, str(BIN))

import rc_request as rq  # noqa: E402


def p(msg):
    global PASS; PASS += 1
    print(f'  PASS: {msg}')


def f(msg):
    global FAIL; FAIL += 1
    print(f'  FAIL: {msg}')


def check(cond, msg):
    p(msg) if cond else f(msg)


print('\n--- validate ---')
check(rq.validate('rc dairy') is None, 'rc dairy ok')
check(rq.validate('rc create step-counter 2') is None, 'four-word create ok')
check(rq.validate('RC list') is None, 'case-insensitive')
check(rq.validate('rc dairy; rm -rf x') is not None, 'shell-ish extra words rejected (too many words)')
check(rq.validate('deploy dairy') is not None, 'non-rc text rejected')
check(rq.validate('rc dairy\nrc stop dairy') is not None, 'multi-line rejected')
check(rq.validate('rc ' + 'x' * 300) is not None, 'over-long rejected')
check(rq.validate('takeover') is not None, 'bare takeover rejected')

print('\n--- write_request ---')
d = Path(tempfile.mkdtemp(prefix='rcreq-'))
rid = rq.write_request('  rc dairy 2 ', '123', d)
files = list(d.glob('*.json'))
check([x.name for x in files] == [f'{rid}.json'], 'one json file named by id')
data = json.loads(files[0].read_text(encoding='utf-8'))
check(data['command'] == 'rc dairy 2' and data['channel'] == '123', 'command stripped, channel kept')
check(data['source'] == 'router' and isinstance(data['ts'], float), 'source + timestamp recorded')
check(list(d.glob('*.tmp')) == [], 'no temp file left')

print('\n--- CLI ---')
r = subprocess.run([sys.executable, str(BIN / 'rc_request.py'), '--roots'], capture_output=True, text=True)
check(r.returncode == 0 and r.stdout.startswith('1. '), 'roots listed, numbered from 1')
r = subprocess.run([sys.executable, str(BIN / 'rc_request.py'), 'deploy dairy', '--channel', '1'],
                   capture_output=True, text=True)
check(r.returncode == 2 and r.stdout.startswith('ERROR'), 'invalid command -> ERROR, exit 2')

print('=' * 50)
print(f'Results: {PASS} passed, {FAIL} failed')
sys.exit(0 if FAIL == 0 else 1)
