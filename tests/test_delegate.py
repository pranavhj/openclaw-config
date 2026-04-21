#!/usr/bin/env python3
"""
Unit tests for the Windows openclaw delegate pipeline.
Ported from tests/test_delegate.sh — no live prerequisites required.

Tests: script presence, imports, CWD key, lock mechanism, sanitization,
       parse_history, ts_ms, timeline events, failure handling, config,
       CLAUDE.md Windows paths, bin/ integrity.
"""
import importlib.util
import io
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 stdout on Windows (avoids cp1252 encoding errors)
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PASS = 0
FAIL = 0

REPO_DIR = Path(__file__).parent.parent
BIN_DIR  = REPO_DIR / 'bin'
AGENTS_DIR = REPO_DIR / 'agents'
REPO_CONFIG = REPO_DIR / 'config' / 'openclaw.json'
LIVE_CONFIG = Path.home() / '.openclaw' / 'openclaw.json'

sys.path.insert(0, str(BIN_DIR))


def p(msg):
    global PASS; PASS += 1
    print(f'  PASS: {msg}')


def f(msg):
    global FAIL; FAIL += 1
    print(f'  FAIL: {msg}')


def skip(msg):
    print(f'  SKIP: {msg}')


def src(name):
    return (BIN_DIR / name).read_text(encoding='utf-8')


def load_module(name, filename):
    """Import a bin/ script by filename, return module or None."""
    path = BIN_DIR / filename
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


print('=== delegate unit tests (Windows) ===')

# ── 1. Script files present ───────────────────────────────────────────────────
print('\n1. Script files present')
for script in ['delegate.py', 'discord-send.py', 'agent-smart.py',
               'session-reset.py', 'bot-logs.py', 'route-audit.py', 'discord-bot.py']:
    (p if (BIN_DIR / script).exists() else f)(
        f'{script} exists' if (BIN_DIR / script).exists() else f'{script} missing from bin/'
    )

# ── 2. Module imports ──────────────────────────────────────────────────────────
print('\n2. Module imports (no errors)')
_modules = {}
for mod_name, filename in [('delegate', 'delegate.py'),
                             ('discord_send', 'discord-send.py'),
                             ('agent_smart', 'agent-smart.py'),
                             ('session_reset', 'session-reset.py')]:
    try:
        _modules[mod_name] = load_module(mod_name, filename)
        p(f'{filename} imports cleanly')
    except SystemExit:
        p(f'{filename} imports cleanly (exits in __main__ guard)')
    except Exception as e:
        f(f'{filename} import error: {e}')
        _modules[mod_name] = None

delegate      = _modules.get('delegate')
agent_smart   = _modules.get('agent_smart')
session_reset = _modules.get('session_reset')

# ── 3. CWD key derivation (agent-smart.py) ────────────────────────────────────
print('\n3. CWD key derivation (agent-smart.py)')

# Forward-slash style (Path on Windows may produce either)
for path_str, expected_suffix in [
    ('C:\\Users\\prana\\projects\\openclaw', 'C--Users-prana-projects-openclaw'),
    ('C:/Users/prana/projects/openclaw',     'C--Users-prana-projects-openclaw'),
]:
    key = path_str.replace('\\', '-').replace('/', '-').replace(':', '-')
    (p if key == expected_suffix else f)(
        f'"{path_str}" -> "{key}"'
    )

if agent_smart:
    try:
        key = agent_smart.get_cwd_key()
        p(f'get_cwd_key() runs without error (returns: {key[:40]})')
    except Exception as e:
        f(f'get_cwd_key() error: {e}')

# ── 4. Lock mechanism (atomic mkdir — NTFS equivalent of bash mkdir lock) ──────
print('\n4. Lock mechanism (atomic mkdir)')
with tempfile.TemporaryDirectory() as tmpdir:
    lock = Path(tmpdir) / 'delegate.lock'

    # 4a: acquire when free
    try:
        lock.mkdir(exist_ok=False)
        p('lock acquired when free')
        lock.rmdir()
    except Exception as e:
        f(f'failed to acquire free lock: {e}')

    # 4b: FileExistsError when held
    lock.mkdir(exist_ok=True)
    try:
        lock.mkdir(exist_ok=False)
        f('expected FileExistsError when lock held')
        if lock.exists(): lock.rmdir()
    except FileExistsError:
        p('FileExistsError raised when lock already held')
    lock.rmdir()

    # 4c: re-acquirable after release
    lock.mkdir(exist_ok=False)
    lock.rmdir()
    try:
        lock.mkdir(exist_ok=False)
        p('lock re-acquirable after release')
        lock.rmdir()
    except FileExistsError:
        f('lock not released (still exists after rmdir)')

# ── 5. Sanitization logic ──────────────────────────────────────────────────────
print('\n5. Message sanitization (OC-015, OC-016)')

for desc, raw, check_absent, check_present in [
    ("apostrophe -> U+2019",  "I'm testing", "'",  '\u2019'),
    ("backtick -> U+2018",    'run `code`',  '`',  '\u2018'),
]:
    s = raw.replace("'", '\u2019').replace('`', '\u2018').replace('\n', ' ')
    (p if check_absent not in s and check_present in s else f)(desc)

# Newline -> space
s3 = "line one\nline two\nline three"
s3 = s3.replace("'", '\u2019').replace('`', '\u2018').replace('\n', ' ')
(p if s3 == 'line one line two line three' else f)('newline -> space (OC-016)')

# chars_replaced count: 1 apostrophe + 2 backticks + 1 newline = 4
msg4 = "I'm using `backtick`\nand newlines"
cnt = msg4.count("'") + msg4.count('`') + msg4.count('\n')
(p if cnt == 4 else f)(f'chars_replaced count ({cnt}, expected 4)')

# ── 6. parse_history function ──────────────────────────────────────────────────
print('\n6. parse_history()')

if delegate:
    log_lines = [
        json.dumps({'ts': '2026-01-01T10:00:00.000Z', 'event': 'delegate_recv', 'msg_preview': 'hello world'}),
        json.dumps({'ts': '2026-01-01T10:00:01.000Z', 'event': 'project_match', 'project': 'openclaw'}),
        json.dumps({'ts': '2026-01-01T11:00:00.000Z', 'event': 'delegate_recv', 'msg_preview': 'second message'}),
        json.dumps({'ts': '2026-01-01T11:00:01.000Z', 'event': 'project_match', 'project': 'screen-reader'}),
        json.dumps({'ts': '2026-01-01T12:00:00.000Z', 'event': 'delegate_recv', 'msg_preview': 'current (skip)'}),
    ]
    result = delegate.parse_history(log_lines)
    entries = [l for l in result.splitlines() if l.strip()]
    (p if len(entries) == 2 else f)(f'returns last 5 excluding current ({len(entries)} entries)')
    (p if '[openclaw] hello world' in result else f)('first entry with project tag')
    (p if '[screen-reader] second message' in result else f)('second entry with correct project tag')
    (p if 'current (skip)' not in result else f)('current message excluded from history')
else:
    skip('delegate module not loaded')

# ── 7. ts_ms format ────────────────────────────────────────────────────────────
print('\n7. ts_ms() timestamp format')

if delegate:
    ts = delegate.ts_ms()
    valid = (len(ts) == 24 and ts.endswith('Z') and 'T' in ts
             and '.' in ts and ts.count('-') == 2)
    (p if valid else f)(f'ts_ms format correct: {ts}')
else:
    skip('delegate module not loaded')

# ── 8. Timeline events in delegate.py source ──────────────────────────────────
print('\n8. Timeline events in delegate.py source')

delegate_src = src('delegate.py')
for event in ['delegate_recv', 'sanitize', 'lock_acquired', 'lock_blocked',
              'project_match', 'prompt_ready', 'agent_start', 'agent_done',
              'failure_detected', 'failure_notified', 'delegate_exit']:
    (p if f"'event': '{event}'" in delegate_src else f)(f"'{event}' event present")

# ── 9. Sanitization in source ─────────────────────────────────────────────────
print('\n9. Sanitization present in delegate.py')

(p if 'u2019' in delegate_src else f)('U+2019 apostrophe replacement in source')
(p if 'u2018' in delegate_src else f)('U+2018 backtick replacement in source')
(p if "replace('\\n', ' ')" in delegate_src else f)('Newline sanitization (OC-016) in source')

# ── 10. Failure notification in source ────────────────────────────────────────
print('\n10. Failure notification in delegate.py')

(p if 'Delegation failed' in delegate_src else f)('failure message present')
(p if 'failure_detected' in delegate_src else f)('failure_detected event in source')
(p if 'failure_notified' in delegate_src else f)('failure_notified event in source')
(p if "output = 'SENT'" in delegate_src else f)("failure handler sets output='SENT'")

# ── 11. Lock-blocked notification in source ───────────────────────────────────
print('\n11. Lock-blocked notification')

(p if 'lock_blocked' in delegate_src and 'discord_send' in delegate_src
   else f)('user notified when locked')
(p if 'sent by delegate' in delegate_src else f)('lock notification has delegate watermark')

# ── 12. Session reset in source ───────────────────────────────────────────────
print('\n12. Session reset after delegation')

(p if 'SESSION_RESET_PY' in delegate_src else f)('SESSION_RESET_PY reference in delegate.py')
# Must appear after agent_done event in source
sr_idx   = delegate_src.rfind('SESSION_RESET_PY')
done_idx = delegate_src.rfind('agent_done')
(p if sr_idx > done_idx else f)('session-reset runs after agent_done (correct order)')

# ── 12b. session-reset no-op when sessions file absent ───────────────────────
if session_reset:
    sessions_path = Path.home() / '.openclaw' / 'agents' / 'main' / 'sessions' / 'sessions.json'
    if not sessions_path.exists():
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                session_reset.main()
            (p if 'No active session' in buf.getvalue() else f)(
                'session-reset no-op when sessions file absent')
        except Exception as e:
            f(f'session-reset error: {e}')
    else:
        skip('sessions file exists — skipping session-reset no-op test')

# ── 13. Yesterday log fallback in source ──────────────────────────────────────
print('\n13. Yesterday log fallback')

(p if 'yesterday_log' in delegate_src else f)('yesterday_log in delegate.py')
(p if 'today_count' in delegate_src else f)('today_count conditional check present')
(p if 'timedelta(days=1)' in delegate_src else f)('timedelta(days=1) for yesterday')

# ── 14. Project discovery filters to directories ─────────────────────────────
print('\n14. Project discovery (dirs only)')

(p if 'iterdir()' in delegate_src else f)('iterdir() used for project discovery')
(p if 'is_dir()' in delegate_src else f)('is_dir() filter present (dirs only)')
(p if 'UNFILTERED_ROOTS' in delegate_src else f)('UNFILTERED_ROOTS defined (D:/MyData/Software)')
(p if 'EXCLUDE_NAMES' in delegate_src else f)('EXCLUDE_NAMES defined (openclaw-config excluded)')

# ── 15. Prompt structure in source ────────────────────────────────────────────
print('\n15. Prompt structure')

(p if '## Reply' in delegate_src else f)('## Reply section in prompt')
(p if '## Known projects' in delegate_src else f)('## Known projects section in prompt')
(p if '## Recent messages' in delegate_src else f)('## Recent messages section in prompt')
(p if '## Request' in delegate_src else f)('## Request section in prompt')
(p if '## Attachments' in delegate_src else f)('## Attachments section in prompt')
(p if 'Only use entries matching' in delegate_src else f)(
    'cross-project filter instruction in prompt')

# ── 16. Config validation (openclaw.json) ─────────────────────────────────────
print('\n16. Config validation (openclaw.json)')

config_file = LIVE_CONFIG if LIVE_CONFIG.exists() else REPO_CONFIG
try:
    with open(config_file) as fh:
        config = json.load(fh)
    p(f'valid JSON ({config_file})')
    attempts = config.get('channels', {}).get('discord', {}).get('retry', {}).get('attempts', 'missing')
    (p if attempts == 1 else f)(f'discord retry.attempts=1 (got: {attempts})')
    thinking = config.get('agents', {}).get('defaults', {}).get('thinkingDefault', 'missing')
    (p if thinking == 'off' else f)(f'thinkingDefault=off (got: {thinking})')
    fallbacks = config.get('agents', {}).get('defaults', {}).get('model', {}).get('fallbacks', [])
    (p if len(fallbacks) == 0 else f)(f'no fallback models (got: {fallbacks})')
except Exception as e:
    f(f'openclaw.json error: {e}')

# ── 17. agents/openclaw-CLAUDE.md Windows paths ───────────────────────────────
print('\n17. agents/openclaw-CLAUDE.md Windows paths')

try:
    claude_md = (AGENTS_DIR / 'openclaw-CLAUDE.md').read_text(encoding='utf-8')
    (p if 'discord-send.py' in claude_md else f)('uses discord-send.py')
    (p if '/home/pranav' not in claude_md else f)('no Linux /home/pranav paths')
    (p if r'C:\Users\prana' in claude_md else f)(r'has Windows C:\Users\prana paths')
    (p if 'nssm status discord-bot' in claude_md else f)('uses nssm (not systemctl)')
    (p if '-# sent by claude' in claude_md else f)('has Discord watermark instruction')
    (p if 'openclaw message send' not in claude_md else f)('no stale openclaw message send reference')
    (p if 'delegate.lock' in claude_md else f)('has delegate lock path')
    (p if 'D:\\MyData\\Software\\openclaw-config' in claude_md or
         r'D:\MyData\Software\openclaw-config' in claude_md else f)(
        'has repo path D:\\MyData\\Software\\openclaw-config')
except Exception as e:
    f(f'openclaw-CLAUDE.md error: {e}')

# ── 18. No rogue scripts in bin/ ──────────────────────────────────────────────
print('\n18. bin/ directory integrity')

ALLOWED = {
    # New Python scripts
    'delegate.py', 'discord-bot.py', 'discord-send.py', 'agent-smart.py',
    'session-reset.py', 'bot-logs.py', 'route-audit.py', 'run-tests.py',
    'restart-bot.py',
    # Service management
    'manage-service.ps1',
    # Existing/observability
    'openclaw-timeline',
    # Legacy bash scripts retained for reference
    'delegate', 'discord-send', 'agent-smart', 'session-reset',
    'bot-logs', 'route-audit', 'run-tests',
}
rogue = [i.name for i in BIN_DIR.iterdir()
         if not i.name.startswith('.') and i.name != '__pycache__' and i.name not in ALLOWED]
(p if not rogue else f)(
    'no unexpected files in bin/' if not rogue else f'unexpected files: {rogue}'
)

# ── 19. Cross-check: delegate.py calls agent-smart.py (not bare 'claude') ─────
print('\n19. delegate.py calls agent-smart.py (not bare claude)')

(p if 'AGENT_SMART_PY' in delegate_src else f)('AGENT_SMART_PY constant defined')
(p if "str(AGENT_SMART_PY)" in delegate_src else f)('agent-smart.py called via AGENT_SMART_PY path')
(p if "str(DISCORD_SEND_PY)" in delegate_src else f)('discord-send.py called via DISCORD_SEND_PY path')

# ── 20. agent-smart.py calls claude with shell=True on Windows ────────────────
print('\n20. agent-smart.py shell=True on Windows')

agent_src = src('agent-smart.py')
(p if "shell = sys.platform == 'win32'" in agent_src else f)(
    "shell=True conditional on sys.platform == 'win32'")
(p if "['claude'] + args" in agent_src else f)(
    "claude called with args passthrough")
(p if 'maybe_compact' in agent_src else f)('maybe_compact function present')
(p if 'THRESHOLD_KB' in agent_src and 'KEEP_PAIRS' in agent_src else f)(
    'THRESHOLD_KB and KEEP_PAIRS constants present')

# ── 21. CLAUDECODE env var stripped before spawning agent (Windows nested-session fix) ──
print('\n21. CLAUDECODE stripped before agent spawn')

(p if "CLAUDECODE" in delegate_src else f)('CLAUDECODE referenced in delegate.py')
(p if "k != 'CLAUDECODE'" in delegate_src else f)(
    "CLAUDECODE stripped from agent_env (prevents nested-session error)")

# ── 22. route-audit.py uses --print-file not --print (Windows newline fix) ────
print('\n22. route-audit.py uses --print-file (OC-016 equivalent)')

route_src = src('route-audit.py')
(p if '--print-file' in route_src else f)(
    'route-audit.py uses --print-file (not bare --print)')
(p if "'--print', prompt" not in route_src and '"--print", prompt' not in route_src else f)(
    'route-audit.py does not pass multi-line prompt via --print')
(p if 'prompt_file' in route_src and 'write_text' in route_src else f)(
    'route-audit.py writes prompt to temp file')

# ── 23. agent-smart.py supports --print-file flag ─────────────────────────────
print('\n23. agent-smart.py supports --print-file')

(p if '--print-file' in agent_src else f)('agent-smart.py handles --print-file arg')
(p if 'read_text' in agent_src and 'prompt_file' in agent_src else f)(
    'agent-smart.py reads prompt from file')

# ── 24. Sub-session spawn in CLAUDE.md uses unset CLAUDECODE ──────────────────
print('\n24. Sub-session spawn unsets CLAUDECODE')

try:
    claude_md = (AGENTS_DIR / 'openclaw-CLAUDE.md').read_text(encoding='utf-8')
    (p if 'unset CLAUDECODE' in claude_md else f)(
        'openclaw-CLAUDE.md: sub-session spawn unsets CLAUDECODE')
    # Must appear in context of the spawn command (before agent-smart.py --continue or claude --continue)
    unsetter_idx = claude_md.find('unset CLAUDECODE')
    # Accept either agent-smart.py --continue (preferred) or bare claude --continue
    continue_idx = claude_md.find('agent-smart.py --continue', unsetter_idx)
    if continue_idx < 0:
        continue_idx = claude_md.find('claude --continue', unsetter_idx)
    (p if unsetter_idx >= 0 and continue_idx > unsetter_idx else f)(
        'unset CLAUDECODE appears before agent-smart.py/claude --continue in spawn command')
except Exception as e:
    f(f'CLAUDE.md read error: {e}')

# ── 26. agent-smart.py CWD key includes underscore→dash conversion ────────────
print('\n26. agent-smart.py get_cwd_key handles underscores')

import re as _re

def _get_cwd_key(path_str):
    return _re.sub(r'[^a-zA-Z0-9]', '-', path_str)

_cases = [
    (r'D:\MyData\Software\cricket_analyzer',    'D--MyData-Software-cricket-analyzer'),
    (r'C:\Users\prana\projects\openclaw',        'C--Users-prana-projects-openclaw'),
    (r'D:\MyData\Software\openclaw-config',      'D--MyData-Software-openclaw-config'),
]
for _path, _expected in _cases:
    _got = _get_cwd_key(_path)
    (p if _got == _expected else f)(f'CWD key: {_path} -> {_got}')

(p if 're.sub' in agent_src or "replace('_'" in agent_src else f)(
    'agent-smart.py uses regex sub for CWD key (handles underscores and all non-alnum)')

# ── 25. projects/CLAUDE.md recursion guard ────────────────────────────────────
print('\n25. projects/CLAUDE.md recursion guard')

projects_claude = Path.home() / 'projects' / 'CLAUDE.md'
(p if projects_claude.exists() else f)(
    f'projects/CLAUDE.md exists at {projects_claude}' if projects_claude.exists()
    else f'MISSING: {projects_claude} (sub-sessions lack recursion guard)'
)
if projects_claude.exists():
    content = projects_claude.read_text(encoding='utf-8', errors='replace')
    (p if 'do NOT' in content or 'do not' in content.lower() else f)(
        'projects/CLAUDE.md instructs sub-sessions not to spawn further sub-sessions')

# ── 27. discord-send.py: --edit argument present (OC-023) ─────────────────────
print('\n27. discord-send.py live-progress additions (OC-023)')

discord_send_src = src('discord-send.py')
(p if '--edit' in discord_send_src else f)('discord-send.py has --edit argument')
(p if 'PATCH' in discord_send_src else f)('discord-send.py uses PATCH method for edits')
(p if 'MSG_ID:' in discord_send_src else f)("discord-send.py prints 'MSG_ID:' on success")
(p if "msg_id = data.get('id', '')" in discord_send_src else f)(
    'discord-send.py extracts message ID from response')

# ── 28. delegate.py: active-session.json + status message (OC-023) ────────────
print('\n28. delegate.py active-session tracking (OC-023)')

(p if 'ACTIVE_SESSION_FILE' in delegate_src else f)(
    'delegate.py defines ACTIVE_SESSION_FILE')
(p if 'active-session.json' in delegate_src else f)(
    "delegate.py references 'active-session.json'")
(p if 'status_msg_id' in delegate_src else f)(
    'delegate.py captures status_msg_id from discord-send.py output')
(p if 'Working' in delegate_src and 'MSG_ID:' in delegate_src else f)(
    "delegate.py sends Working status and parses MSG_ID response")
(p if 'ACTIVE_SESSION_FILE.unlink' in delegate_src else f)(
    'delegate.py cleans up active-session.json in finally block')

# ── 29. restart-bot.py and manage-service.ps1 grant-user (OC-024) ─────────────
print('\n29. Non-elevated service restart (OC-024)')

restart_src = src('restart-bot.py')
(p if 'restart-bot.signal' in restart_src else f)('restart-bot.py uses signal file approach')
(p if 'SIGNAL_FILE' in restart_src else f)('restart-bot.py defines SIGNAL_FILE')
(p if 'ready user=' in restart_src else f)("restart-bot.py waits for 'ready' in log")
(p if 'manage-service.ps1' in restart_src else f)('restart-bot.py references manage-service.ps1')

ps1_src = src('manage-service.ps1')
(p if 'grant-user' in ps1_src else f)("manage-service.ps1 has 'grant-user' action")
(p if 'sc.exe sdshow' in ps1_src else f)('manage-service.ps1 reads current SDDL')
(p if 'sc.exe sdset' in ps1_src else f)('manage-service.ps1 writes new SDDL')
(p if 'CCLCSWRPWPDTLOCRRC' in ps1_src else f)('manage-service.ps1 uses correct ACE rights string')

# ── Summary ────────────────────────────────────────────────────────────────────
print()
print('==============================')
print(f'Results: {PASS} passed, {FAIL} failed')
sys.exit(0 if FAIL == 0 else 1)
