#!/usr/bin/env python3
"""
Unit tests for bin/rc_sessions.py (OC-041, case 3: start Remote Control in a folder).

No live prerequisites. Uses tempdir config/session files; never touches ~/.claude.json.
"""
import io
import json
import sys
import tempfile
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PASS = 0
FAIL = 0
REPO_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_DIR / 'bin'))

import rc_sessions as rc  # noqa: E402


def p(msg):
    global PASS; PASS += 1
    print(f'  PASS: {msg}')


def f(msg):
    global FAIL; FAIL += 1
    print(f'  FAIL: {msg}')


def check(cond, msg):
    p(msg) if cond else f(msg)


tmp = Path(tempfile.mkdtemp(prefix='rc-test-'))
proj = tmp / 'myproj'
proj.mkdir()

print('\n--- config_key ---')
key = rc.config_key(proj)
check('\\' not in key and key.endswith('/myproj'), f'forward-slash key: {key}')

print('\n--- ensure_trusted ---')
cfg = tmp / 'claude.json'
cfg.write_text(json.dumps({'projects': {'X:/other': {'hasTrustDialogAccepted': True}},
                           'otherSetting': 7}), encoding='utf-8')
check(not rc.is_trusted(proj, cfg), 'untrusted before')
check(rc.ensure_trusted(proj, cfg), 'ensure_trusted returns True')
check(rc.is_trusted(proj, cfg), 'trusted after')
data = json.loads(cfg.read_text(encoding='utf-8'))
check(data.get('otherSetting') == 7 and 'X:/other' in data['projects'], 'other config preserved')
check(not (tmp / 'claude.json.rc-tmp').exists(), 'temp file cleaned up')
check(rc.ensure_trusted(proj, cfg), 'idempotent when already trusted')
check(not rc.is_trusted(proj, tmp / 'missing.json'), 'missing config -> untrusted, no crash')

print('\n--- parse_job_id ---')
out = 'Starting background service…\nbackgrounded · 9eb17721 · rc-trust-test (idle — send a prompt to start)\n'
check(rc.parse_job_id(out) == '9eb17721', 'parses job id with name')
check(rc.parse_job_id('backgrounded · 205f3a58\n  claude agents') == '205f3a58', 'parses job id without name')
check(rc.parse_job_id('Workspace not trusted.') is None, 'None on failure output')

print('\n--- build_start_cmd ---')
rc.claude_exe = lambda: 'claude'
cmd = rc.build_start_cmd('myproj')
check(cmd == ['claude', '--bg', '--remote-control', '-n', 'myproj', '--permission-mode', 'bypassPermissions'],
      f'fresh cmd: {cmd}')
cmd = rc.build_start_cmd('myproj', resume_id='abc', permission_mode='default')
check(cmd[:4] == ['claude', '--bg', '--resume', 'abc'] and cmd[-1] == 'default', f'resume cmd: {cmd}')

print('\n--- find_session / wait_for_bridge ---')
sdir = tmp / 'sessions'
sdir.mkdir()
(sdir / '1.json').write_text(json.dumps({'jobId': 'aaaa1111', 'sessionId': 's1'}), encoding='utf-8')
(sdir / '2.json').write_text('{not json', encoding='utf-8')
(sdir / '3.json').write_text(json.dumps({'jobId': 'bbbb2222', 'sessionId': 's3',
                                         'bridgeSessionId': 'session_XYZ'}), encoding='utf-8')
check(rc.find_session('aaaa1111', sdir)['sessionId'] == 's1', 'finds by jobId, skips corrupt file')
check(rc.find_session('nope', sdir) is None, 'unknown job -> None')
check(rc.wait_for_bridge('bbbb2222', 2, 0.1, sdir)['bridgeSessionId'] == 'session_XYZ', 'bridge ready')
check(rc.wait_for_bridge('aaaa1111', 0.5, 0.1, sdir) is None, 'no bridge -> None after timeout')

print('\n--- start_rc errors ---')
try:
    rc.start_rc(tmp / 'does-not-exist')
    f('missing folder should raise')
except rc.RCError:
    p('missing folder raises RCError')

print('=' * 50)
print(f'Results: {PASS} passed, {FAIL} failed')
sys.exit(0 if FAIL == 0 else 1)
