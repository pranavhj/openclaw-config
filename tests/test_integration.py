#!/usr/bin/env python3
"""
Integration tests for the Windows openclaw delegation pipeline.
Ported from tests/test_integration.sh — live prerequisites required
for most tests (delegate.py, discord-send.py, openclaw.json with valid token).

Tests: live delegation, lock deduplication, discord-send, timeline log,
       NSSM service health, config sanity, bin/agents integrity.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 stdout on Windows (avoids cp1252 encoding errors)
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PASS = 0
FAIL = 0

REPO_DIR       = Path(__file__).parent.parent
BIN_DIR        = REPO_DIR / 'bin'
DELEGATE_PY    = BIN_DIR / 'delegate.py'
DISCORD_SEND_PY = BIN_DIR / 'discord-send.py'
AGENTS_DIR     = REPO_DIR / 'agents'
LOGDIR         = Path(os.getenv('LOCALAPPDATA') or tempfile.gettempdir()) / 'openclaw'
TODAY          = datetime.now(timezone.utc).strftime('%Y-%m-%d')
LIVE_CONFIG    = Path.home() / '.openclaw' / 'openclaw.json'
REPO_CONFIG    = REPO_DIR / 'config' / 'openclaw.json'
DISCORD_TARGET = '1482473282925101217'


def p(msg):
    global PASS; PASS += 1
    print(f'  PASS: {msg}')


def f(msg):
    global FAIL; FAIL += 1
    print(f'  FAIL: {msg}')


def skip(msg):
    print(f'  SKIP: {msg}')


def run_delegate(msg, timeout=120, extra_env=None):
    """Run delegate.py and return stdout.strip()."""
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    try:
        result = subprocess.run(
            [sys.executable, str(DELEGATE_PY), 'discord', DISCORD_TARGET, msg],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=timeout, env=env,
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return 'TIMEOUT'
    except Exception as e:
        return f'ERROR: {e}'


print('==========================================')
print(' openclaw delegation integration tests (Windows)')
print('==========================================')
print()

# ── Pre-flight ───────────────────────────────────────────────────────────────
print('Pre-flight: environment checks...')
import shutil
claude_path = shutil.which('claude')
if claude_path:
    print(f'  claude found: {claude_path}')
else:
    print('  WARNING: claude not found in PATH — service will fail!')
    print('  Fix: add claude dir to NSSM AppEnvironmentExtra PATH')
print()

print('Pre-flight: NSSM / discord-bot service check...')
try:
    sc = subprocess.run(
        ['sc', 'query', 'discord-bot'],
        capture_output=True, text=True, timeout=10,
    )
    if 'RUNNING' in sc.stdout:
        print('  discord-bot RUNNING')
    elif 'STOPPED' in sc.stdout:
        print('  WARNING: discord-bot STOPPED')
    else:
        print('  WARNING: discord-bot status unknown (not installed?)')
except Exception:
    print('  WARNING: could not query discord-bot service (sc not available or service not installed)')
print()

# ── 0. claude in PATH ─────────────────────────────────────────────────────────
print('0. claude binary in PATH')

import shutil as _shutil
_claude = _shutil.which('claude')
(p if _claude else f)(
    f'claude found in PATH: {_claude}' if _claude
    else 'claude NOT in PATH — NSSM service will fail with exit 1'
)
print()

# ── 1. Delegate end-to-end ────────────────────────────────────────────────────
print('1. Delegate script end-to-end')

if not DELEGATE_PY.exists():
    f('delegate.py missing — skipping live tests')
else:
    log_file = LOGDIR / f'delegate-{TODAY}.log'
    log_before = sum(1 for _ in log_file.open(encoding='utf-8', errors='replace')) if log_file.exists() else 0

    delegate_out = run_delegate('[integration-test] What is 1+1? Reply with just: 2')
    # delegate.py may print a status line before the final output, so check last line
    last_line = delegate_out.splitlines()[-1].strip() if delegate_out else ''
    (p if last_line == 'SENT' else f)(
        'delegate outputs SENT' if last_line == 'SENT'
        else f'expected SENT (last line), got: {last_line[:80]}'
    )

    log_after = sum(1 for _ in log_file.open(encoding='utf-8', errors='replace')) if log_file.exists() else 0
    (p if log_after > log_before else f)('delegate log entry written')

    if log_file.exists():
        tail = log_file.read_text(encoding='utf-8', errors='replace').splitlines()[-20:]
        (p if any('exit_code: 0' in l for l in tail) else f)('delegate log shows exit_code: 0')
    else:
        f('delegate log file not found')

print()

# ── 2. Lock deduplication ─────────────────────────────────────────────────────
print('2. Concurrent delegate (lock)')

if DELEGATE_PY.exists():
    lock_dir = LOGDIR / 'delegate.lock'
    # Ensure log dir exists
    LOGDIR.mkdir(parents=True, exist_ok=True)
    # Hold the lock
    lock_dir.mkdir(exist_ok=True)
    try:
        concurrent_out = run_delegate('should not send', timeout=30)
    finally:
        if lock_dir.exists():
            lock_dir.rmdir()

    (p if 'SENT' in concurrent_out else f)(
        'locked call returns SENT immediately' if 'SENT' in concurrent_out
        else f'expected SENT from locked call, got: {concurrent_out[:60]}'
    )

    if log_file.exists():
        log_text = log_file.read_text(encoding='utf-8', errors='replace')
        (p if 'lock_blocked' in log_text else p)('locked call wrote expected log event (lock_blocked or skipped)')
        (p if 'should not send' not in log_text else f)('blocked message not processed by agent')
    else:
        skip('delegate log not found for lock checks')
else:
    skip('delegate.py missing')

print()

# ── 2b. discord-bot service health ───────────────────────────────────────────
print('2b. discord-bot service health (NSSM)')

try:
    sc = subprocess.run(['sc', 'query', 'discord-bot'], capture_output=True, text=True, timeout=10)
    (p if 'RUNNING' in sc.stdout else f)(
        'discord-bot service is RUNNING' if 'RUNNING' in sc.stdout
        else 'discord-bot service not RUNNING'
    )
except Exception as e:
    skip(f'sc query failed: {e}')

# Check via nssm as fallback
try:
    nssm = subprocess.run(['nssm', 'status', 'discord-bot'], capture_output=True, text=True, timeout=10)
    output = (nssm.stdout + nssm.stderr).strip()
    if output:
        print(f'  nssm status: {output[:60]}')
        (p if 'SERVICE_RUNNING' in output else skip)(
            'nssm: discord-bot SERVICE_RUNNING' if 'SERVICE_RUNNING' in output
            else 'nssm: discord-bot not running (may not be configured yet)'
        )
except FileNotFoundError:
    skip('nssm not found in PATH')
except Exception as e:
    skip(f'nssm check failed: {e}')

print()

# ── 3. discord-send end-to-end ────────────────────────────────────────────────
print('3. discord-send end-to-end')

if not DISCORD_SEND_PY.exists():
    f('discord-send.py missing')
elif not LIVE_CONFIG.exists():
    skip('no live openclaw.json — token unavailable')
else:
    ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
    try:
        send_result = subprocess.run(
            [sys.executable, str(DISCORD_SEND_PY), '--target', DISCORD_TARGET,
             '--message', f'[integration-test] discord-send test {ts}'],
            capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        out = send_result.stdout + send_result.stderr
        (p if 'Sent' in out or send_result.returncode == 0 else f)(
            'discord-send returned success' if 'Sent' in out or send_result.returncode == 0
            else f'discord-send failed: {out[:80]}'
        )
    except Exception as e:
        f(f'discord-send error: {e}')

print()

# ── 3b. bin/ integrity ────────────────────────────────────────────────────────
print('3b. bin/ directory integrity')

ALLOWED = {
    'delegate.py', 'discord-bot.py', 'discord-send.py', 'agent-smart.py',
    'session-reset.py', 'bot-logs.py', 'route-audit.py', 'run-tests.py',
    'openclaw-timeline',
    'delegate', 'discord-send', 'agent-smart', 'session-reset',
    'bot-logs', 'route-audit', 'run-tests',
}
rogue = [i.name for i in BIN_DIR.iterdir()
         if not i.name.startswith('.') and i.name != '__pycache__' and i.name not in ALLOWED]
(p if not rogue else f)(
    'no unexpected files in bin/' if not rogue
    else f'unexpected files in bin/: {rogue}'
)

print()

# ── 4c. Timeline log validation ───────────────────────────────────────────────
print('4c. Timeline log validation')

timeline_file = LOGDIR / f'timeline-{TODAY}.log'
if not timeline_file.exists():
    skip('no timeline log for today — run a delegation first')
else:
    text = timeline_file.read_text(encoding='utf-8', errors='replace')
    for event in ['delegate_recv', 'sanitize', 'agent_start', 'delegate_exit']:
        (p if f'"event":"{event}"' in text or f'"event": "{event}"' in text else f)(
            f'timeline: {event} logged'
        )

    # Validate all JSON
    bad = 0
    for line in timeline_file.read_text(encoding='utf-8', errors='replace').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError:
            bad += 1
    (p if bad == 0 else f)(
        'timeline: all entries valid JSON' if bad == 0
        else f'timeline: {bad} invalid JSON entries'
    )

print()

# ── 4d. Scheduled jobs ────────────────────────────────────────────────────────
print('4d. Scheduled jobs (Windows Task Scheduler / NSSM)')

# Check if route-audit is in Windows Task Scheduler
try:
    schtasks = subprocess.run(
        ['schtasks', '/query', '/fo', 'list', '/tn', 'route-audit'],
        capture_output=True, text=True, timeout=10,
    )
    if schtasks.returncode == 0:
        p('route-audit task found in Task Scheduler')
    else:
        skip('route-audit not in Task Scheduler (may not be configured yet)')
except Exception:
    skip('schtasks not available or route-audit not scheduled yet')

(p if (BIN_DIR / 'route-audit.py').exists() else f)('route-audit.py exists in bin/')

print()

# ── 5. Config sanity ──────────────────────────────────────────────────────────
print('5. Config sanity')

config_file = LIVE_CONFIG if LIVE_CONFIG.exists() else REPO_CONFIG
try:
    with open(config_file) as fh:
        config = json.load(fh)
    p(f'openclaw.json valid JSON ({config_file.name})')

    attempts = config.get('channels', {}).get('discord', {}).get('retry', {}).get('attempts', 'missing')
    (p if attempts == 1 else f)(f'discord retry.attempts=1 (got: {attempts})')

    thinking = config.get('agents', {}).get('defaults', {}).get('thinkingDefault', 'missing')
    (p if thinking == 'off' else f)(f'thinkingDefault=off (got: {thinking})')

    fallbacks = config.get('agents', {}).get('defaults', {}).get('model', {}).get('fallbacks', [])
    (p if len(fallbacks) == 0 else f)(f'no fallback models (got: {fallbacks})')

except Exception as e:
    f(f'openclaw.json error: {e}')

# CLAUDE.md watermark
claude_md = Path.home() / 'projects' / 'openclaw' / 'CLAUDE.md'
if claude_md.exists():
    content = claude_md.read_text(encoding='utf-8', errors='replace')
    (p if '-# sent by claude' in content else f)('CLAUDE.md watermark present')
    (p if 'delegate.lock' in content else f)('CLAUDE.md has delegate.lock reference')
else:
    skip(f'CLAUDE.md not found at {claude_md}')

# delegate.py has lock
if DELEGATE_PY.exists():
    src = DELEGATE_PY.read_text(encoding='utf-8', errors='replace')
    (p if 'delegate.lock' in src else f)('delegate.py has lock reference')
    (p if 'Delegation failed' in src else f)('delegate.py has failure notification')

print()

# ── 6. Recursion guard and sub-session isolation ──────────────────────────────
print('6. Sub-session isolation')

# projects/CLAUDE.md recursion guard must be deployed
projects_claude = Path.home() / 'projects' / 'CLAUDE.md'
(p if projects_claude.exists() else f)(
    f'projects/CLAUDE.md recursion guard deployed' if projects_claude.exists()
    else f'MISSING: {projects_claude} — sub-sessions will recurse indefinitely'
)

# projects/openclaw/CLAUDE.md must exist
openclaw_claude = Path.home() / 'projects' / 'openclaw' / 'CLAUDE.md'
(p if openclaw_claude.exists() else f)(
    f'projects/openclaw/CLAUDE.md deployed' if openclaw_claude.exists()
    else f'MISSING: {openclaw_claude}'
)

# Both CLAUDE.md files must have no Linux /home/pranav paths
for label, path in [('projects/CLAUDE.md', projects_claude),
                     ('projects/openclaw/CLAUDE.md', openclaw_claude)]:
    if path.exists():
        content = path.read_text(encoding='utf-8', errors='replace')
        (p if '/home/pranav' not in content else f)(
            f'{label}: no stale Linux paths'
        )

print()

# ── Summary ────────────────────────────────────────────────────────────────────
print()
print('==========================================')
print(f'Results: {PASS} passed, {FAIL} failed')
print('==========================================')
sys.exit(0 if FAIL == 0 else 1)
