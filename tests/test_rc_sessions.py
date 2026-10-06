#!/usr/bin/env python3
"""
Unit tests for bin/rc_sessions.py (OC-041, case 3: start Remote Control in a folder).

No live prerequisites. Uses tempdir config/session files; never touches ~/.claude.json.
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
_me = os.getpid()
_me_start = rc.proc_start_time(_me)
(sdir / '3.json').write_text(json.dumps({'jobId': 'bbbb2222', 'sessionId': 's3', 'pid': _me,
                                         'procStart': str(_me_start),
                                         'bridgeSessionId': 'session_XYZ'}), encoding='utf-8')
# dead process left its record behind (same job id, bridge id set) -- must never count as ready
(sdir / '4.json').write_text(json.dumps({'jobId': 'cccc3333', 'sessionId': 's4', 'pid': _me,
                                         'procStart': str(_me_start + 1),
                                         'bridgeSessionId': 'session_OLD'}), encoding='utf-8')
check(rc.find_session('aaaa1111', sdir)['sessionId'] == 's1', 'finds by jobId, skips corrupt file')
check(rc.find_session('nope', sdir) is None, 'unknown job -> None')
check(rc.wait_for_bridge('bbbb2222', 2, 0.1, sdir)['bridgeSessionId'] == 'session_XYZ', 'live bridge ready')
check(rc.wait_for_bridge('aaaa1111', 0.5, 0.1, sdir) is None, 'no bridge -> None after timeout')
check(rc.wait_for_bridge('cccc3333', 0.5, 0.1, sdir) is None, 'dead record with bridge id -> not ready')
(sdir / '5.json').write_text(json.dumps({'jobId': 'cccc3333', 'sessionId': 's4', 'pid': _me,
                                         'procStart': str(_me_start),
                                         'bridgeSessionId': 'session_NEW'}), encoding='utf-8')
check(rc.wait_for_bridge('cccc3333', 2, 0.1, sdir)['bridgeSessionId'] == 'session_NEW',
      'dead + live record for same job -> the live one wins')

print('\n--- start_rc errors ---')
try:
    rc.start_rc(tmp / 'does-not-exist')
    f('missing folder should raise')
except rc.RCError:
    p('missing folder raises RCError')

print('\n--- review fixes ---')
check(rc.parse_job_id('backgrounded · ABCDEF0123 · x') == 'abcdef0123', 'longer/uppercase job id not truncated')
check(rc.safe_name('R&D 50%x') == 'R_D_50_x', 'cmd.exe metachars stripped from name')
check(rc.safe_name('') == 'session', 'empty name -> session')
cfg2 = tmp / 'claude2.json'
cfg2.write_text(json.dumps({'projects': {}}), encoding='utf-8')
_orig_sig = rc._stat_sig
_calls = {'n': 0}


def _flaky_sig(path):
    _calls['n'] += 1
    return (_calls['n'], 0)  # every stat differs -> "file changed under us" on each attempt


rc._stat_sig = _flaky_sig
check(not rc.ensure_trusted(proj, cfg2, attempts=2), 'concurrent change -> no write, gives up')
check(json.loads(cfg2.read_text(encoding='utf-8')) == {'projects': {}}, 'config untouched when it kept changing')
rc._stat_sig = _orig_sig
check(list(tmp.glob('.claude.json.rc-*')) == [], 'no temp files left after aborted writes')

print('\n--- transcripts ---')
troot = tmp / 'tprojects'
key = rc.re.sub(r'[^A-Za-z0-9]', '-', str(proj.resolve()))
tdir = troot / key.lower()  # stored with different case, like 'c--Users-...'
tdir.mkdir(parents=True)
check(rc.transcript_dir(proj, troot) == tdir, 'transcript dir matched case-insensitively')
check(rc.transcript_dir(tmp / 'nope', troot) is None, 'no transcript dir -> None')
lines = [
    {'type': 'user', 'entrypoint': 'cli', 'message': {'content': 'fix the login bug please'}},
    {'type': 'assistant', 'entrypoint': 'cli', 'message': {'content': [{'type': 'text', 'text': 'ok'}]}},
    {'type': 'user', 'entrypoint': 'cli', 'message': {'content': [{'type': 'tool_result', 'content': 'x'}]}},
    {'type': 'user', 'entrypoint': 'cli', 'isMeta': True, 'message': {'content': 'meta'}},
    {'type': 'user', 'entrypoint': 'cli', 'message': {'content': '<command-name>/clear</command-name>'}},
    {'type': 'ai-title', 'aiTitle': 'Login bug'},
    {'type': 'user', 'entrypoint': 'cli', 'message': {'content': [{'type': 'text', 'text': 'thanks'}]}},
]
(tdir / 'aaaa-1.jsonl').write_text('\n'.join(json.dumps(x) for x in lines) + '\nnot json\n', encoding='utf-8')
(tdir / 'bbbb-2.jsonl').write_text(json.dumps({'type': 'user', 'entrypoint': 'sdk-cli',
                                               'message': {'content': 'deploy apk'}}) + '\n', encoding='utf-8')
(tdir / 'cccc-3.jsonl').write_text(json.dumps({'type': 'summary'}) + '\n', encoding='utf-8')
os.utime(tdir / 'aaaa-1.jsonl', (1000, 1000))
os.utime(tdir / 'bbbb-2.jsonl', (2000, 2000))
s1 = rc.summarize_transcript(tdir / 'aaaa-1.jsonl')
check(s1['title'] == 'Login bug', 'ai-title used')
check(s1['user_turns'] == 2, 'tool results, meta and command wrappers not counted as turns')
check(s1['first_prompt'] == 'fix the login bug please', 'first real prompt')
check(s1['source'] == 'terminal', 'cli -> terminal')
check(rc.summarize_transcript(tdir / 'bbbb-2.jsonl')['source'] == 'discord', 'sdk-cli -> discord')
convs = rc.list_conversations(proj, root=troot)
check([c['session_id'] for c in convs] == ['bbbb-2', 'aaaa-1'], 'newest first, empty transcript skipped')
check([c['session_id'] for c in rc.list_conversations(proj, limit=1, root=troot)] == ['bbbb-2'], 'limit')

print('\n--- resume_rc decisions (CLI mocked) ---')
calls = []
rc.ensure_trusted = lambda path, *a, **k: True
rc.start_rc = lambda path, name=None, resume_id=None, **k: calls.append(('start', resume_id)) or \
    {'url': 'u-start', 'session_id': resume_id}
rc._launch_and_wait = lambda cmd, project, name, t: calls.append(('wake', cmd[-1])) or {'url': 'u-wake'}
rc.bg_session_ids = lambda: {'bg-1'}
rc.session_records = lambda *a, **k: [
    {'sessionId': 'live-rc', 'jobId': 'liverc00', 'bridgeSessionId': 'session_L', 'pid': 1, 'cwd': str(proj)},
    {'sessionId': 'live-term', 'pid': 2, 'status': 'busy', 'kind': 'interactive', 'cwd': str(proj)},
    {'sessionId': 'live-idle', 'pid': 3, 'status': 'idle', 'kind': 'interactive', 'cwd': str(proj)},
    {'sessionId': 'live-bg', 'pid': 4, 'status': 'idle', 'kind': 'bg', 'jobId': 'livebg00', 'cwd': str(proj)},
    {'sessionId': 'live-odd', 'pid': 5, 'status': 'idle', 'cwd': str(proj)},
]
r = rc.resume_rc(proj, 'live-rc')
check(r['reused'] and r['url'] == 'https://claude.ai/code/session_L' and calls == [], 'live RC -> reuse, no launch')
try:
    rc.resume_rc(proj, 'live-term')
    f('live terminal should raise RCLiveElsewhere')
except rc.RCLiveElsewhere as e:
    check(e.status == 'busy' and e.pid == 2, 'live terminal -> RCLiveElsewhere with status/pid')
rc.resume_rc(proj, 'live-term', allow_copy=True)
check(calls[-1] == ('start', 'live-term'), 'allow_copy -> start with --resume (copy)')
rc.resume_rc(proj, 'bg-1')
check(calls[-1] == ('wake', 'bg-1'), 'background session -> wake without flags')
rc.resume_rc(proj, 'old-1')
check(calls[-1] == ('start', 'old-1'), 'closed conversation -> --resume --remote-control')


def _wake_fails(cmd, project, name, t):
    raise rc.RCError('no bridge')


rc._launch_and_wait = _wake_fails
r = rc.resume_rc(proj, 'bg-1')
check(r.get('copied') and calls[-1] == ('start', 'bg-1'), 'bg wake without RC -> copy fallback')

print('\n--- takeover ---')
killed = []
rc.kill_pid = lambda pid, *a, **k: killed.append(pid) or True
rc.record_is_live = lambda rec: True
stopped_jobs = []
rc.stop_job = lambda job: stopped_jobs.append(job) or 'stopped'
try:
    rc.takeover(proj, 'live-odd')
    f('unknown session kind must not be killed')
except rc.RCError as e:
    check('cannot be taken over' in str(e) and killed == [], 'unknown kind refused, nothing killed')
try:
    rc.takeover(proj, 'live-term')
    f('busy terminal must not be taken over')
except rc.RCError as e:
    check('not idle' in str(e) and killed == [], 'busy terminal refused, nothing killed')
_recs_before = rc.session_records
_state = {'killed': False}


def _recs_after_kill(*a, **k):
    return [] if (killed or stopped_jobs) else _recs_before()


rc.session_records = _recs_after_kill
rc.takeover(proj, 'live-idle')
check(killed == [3] and calls[-1] == ('start', 'live-idle'), 'idle terminal killed then resumed same id')
killed.clear()
rc.takeover(proj, 'live-bg')
check(stopped_jobs == ['livebg00'] and killed == [], 'bg session without RC is stopped via CLI, not killed')

print('\n--- record_is_live (pid identity) ---')
import importlib
rc2 = importlib.reload(rc)
me = os.getpid()
real_start = rc2.proc_start_time(me)
check(isinstance(real_start, int), 'proc_start_time returns FILETIME int for own pid')
check(rc2.record_is_live({'pid': me, 'procStart': str(real_start)}), 'matching procStart -> live')
check(not rc2.record_is_live({'pid': me, 'procStart': str(real_start + 1)}), 'reused pid (procStart mismatch) -> not live')
check(not rc2.record_is_live({'pid': 0}), 'no pid -> not live')

print('\n--- create_project ---')
newp = rc.create_project(tmp, 'brandnew')
check((newp / 'PROGRESS.md').exists(), 'PROGRESS.md written (so discovery lists it)')
check((newp / '.git').is_dir(), 'git initialised')
try:
    rc.create_project(tmp, 'brandnew')
    f('existing folder should raise')
except rc.RCError as e:
    check('already exists' in str(e), 'existing folder refused')

print('\n--- registry ---')
reg = tmp / 'reg.json'
rc.registry_add('s1', 'C:/p/a', 'a', reg)
rc.registry_add('s2', 'C:/p/b', 'b', reg)
rc.registry_remove('s1', reg)
check(list(rc.registry_entries(reg)) == ['s2'], 'add/remove')
check(rc.registry_entries(tmp / 'none.json') == {}, 'missing registry -> empty')

print('=' * 50)
print(f'Results: {PASS} passed, {FAIL} failed')
sys.exit(0 if FAIL == 0 else 1)
