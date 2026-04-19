#!/usr/bin/env python3
"""
Tests for CLAUDE.md behavior and project lifecycle — Windows port.
Ported from tests/test_claude_behavior.sh.

Uses OPENCLAW_TEST_CAPTURE_FILE (supported in discord-send.py) to capture
what Claude actually sends to Discord without a mock binary.

Sections:
  A. Message format rules (watermark, tables, URL, special chars, multi-line)
  B. Project lifecycle (one-off, new project, continuation, format)
  C. Routing integrity (no rogue files, CLAUDE.md not modified, timing)

All live tests are skipped if delegate.py exits with error or claude CLI
is absent. Run with OPENCLAW_SKIP_LIVE=1 to force-skip all live tests.
"""
import hashlib
import io
import json
import os
import re
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
SKIP = 0

REPO_DIR        = Path(__file__).parent.parent
BIN_DIR         = REPO_DIR / 'bin'
DELEGATE_PY     = BIN_DIR / 'delegate.py'
DISCORD_TARGET  = '1482473282925101217'
PROJECTS_DIR    = Path.home() / 'projects'
CLAUDE_MD       = PROJECTS_DIR / 'openclaw' / 'CLAUDE.md'
LIVE_CONFIG     = Path.home() / '.openclaw' / 'openclaw.json'

SKIP_LIVE = bool(os.environ.get('OPENCLAW_SKIP_LIVE'))


def p(msg):
    global PASS; PASS += 1
    print(f'  PASS: {msg}')


def f(msg):
    global FAIL; FAIL += 1
    print(f'  FAIL: {msg}')


def sk(msg):
    global SKIP; SKIP += 1
    print(f'  SKIP: {msg}')


def run_delegate(msg, capture_file=None, timeout=120):
    """Run delegate.py, optionally with capture file. Returns stdout.strip()."""
    env = dict(os.environ)
    if capture_file:
        env['OPENCLAW_TEST_CAPTURE_FILE'] = str(capture_file)
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


def last_message(capture_file):
    """Return the most recent captured message from capture_file."""
    if not Path(capture_file).exists():
        return ''
    content = Path(capture_file).read_text(encoding='utf-8', errors='replace')
    parts = [p.strip() for p in content.split('---MSG_SEP---') if p.strip()]
    return parts[-1] if parts else ''


def all_messages(capture_file):
    """Return count of captured messages."""
    if not Path(capture_file).exists():
        return 0
    content = Path(capture_file).read_text(encoding='utf-8', errors='replace')
    return len([p for p in content.split('---MSG_SEP---') if p.strip()])


def check_live():
    """Return True if live tests can run (delegate.py present, config present)."""
    if SKIP_LIVE:
        return False
    if not DELEGATE_PY.exists():
        return False
    if not LIVE_CONFIG.exists():
        return False
    return True


# ── Quick pre-flight ──────────────────────────────────────────────────────────
print('============================================')
print(' CLAUDE.md behavior + project lifecycle tests (Windows)')
print('============================================')
print()
print('Pre-flight checks...')

if not DELEGATE_PY.exists():
    print(f'  WARNING: delegate.py not found at {DELEGATE_PY}')
if not LIVE_CONFIG.exists():
    print(f'  WARNING: openclaw.json not found at {LIVE_CONFIG}')
if not CLAUDE_MD.exists():
    print(f'  WARNING: CLAUDE.md not found at {CLAUDE_MD}')

if check_live():
    print('  Live tests: ENABLED')
else:
    reason = 'OPENCLAW_SKIP_LIVE set' if SKIP_LIVE else 'delegate.py or openclaw.json missing'
    print(f'  Live tests: DISABLED ({reason})')
print()

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION A: CLAUDE.md Message Format Rules
# ═══════════════════════════════════════════════════════════════════════════════
print('A. CLAUDE.md — message format rules')
print()

# ── A1: Watermark ─────────────────────────────────────────────────────────────
print('A1. Watermark (-# sent by claude)')

if not check_live():
    sk('live tests disabled')
else:
    with tempfile.TemporaryDirectory() as tmpdir:
        cap = Path(tmpdir) / 'captures.txt'
        out = run_delegate('[claude-test-watermark] Reply with exactly: ok', capture_file=cap)

        (p if out == 'SENT' else f)(
            'delegate outputs SENT' if out == 'SENT'
            else f'expected SENT stdout, got: {out[:60]}'
        )

        msg = last_message(cap)
        if not msg:
            f('no message captured')
        else:
            print(f'  Captured: {msg[:80]}...')
            lines = msg.splitlines()
            last_line = lines[-1] if lines else ''
            (p if last_line == '-# sent by claude' else f)(
                'watermark is the last line' if last_line == '-# sent by claude'
                else f'watermark missing or not last line (last: {repr(last_line)})'
            )

print()

# ── A2: No markdown tables ────────────────────────────────────────────────────
print('A2. No markdown tables')

if not check_live():
    sk('live tests disabled')
else:
    with tempfile.TemporaryDirectory() as tmpdir:
        cap = Path(tmpdir) / 'captures.txt'
        run_delegate('[claude-test-tables] List 3 differences between Python lists and tuples. Be brief.',
                     capture_file=cap)
        msg = last_message(cap)
        if not msg:
            sk('no message captured')
        else:
            has_table = bool(re.search(r'^\|.+\|$|^\|[-: ]+\|', msg, re.MULTILINE))
            (f if has_table else p)(
                'response contains markdown table (violates Discord format rule)'
                if has_table else 'no markdown tables in response'
            )

print()

# ── A3: URLs wrapped in <> ────────────────────────────────────────────────────
print('A3. URL wrapping (<url>)')

if not check_live():
    sk('live tests disabled')
else:
    with tempfile.TemporaryDirectory() as tmpdir:
        cap = Path(tmpdir) / 'captures.txt'
        run_delegate('[claude-test-url] Give me one link to the Python official docs. Include the URL.',
                     capture_file=cap)
        msg = last_message(cap)
        if not msg:
            sk('no message captured')
        elif 'https://' not in msg:
            sk('no URL in response')
        else:
            urls = re.findall(r'https://[^\s>)]+', msg)
            unwrapped = [u for u in urls if f'<{u}>' not in msg]
            (f if unwrapped else p)(
                f'URL(s) not wrapped in <>: {unwrapped[:2]}'
                if unwrapped else 'all URLs wrapped in <>'
            )

print()

# ── A5: Special characters ────────────────────────────────────────────────────
print("A5. Special characters (apostrophes, double quotes)")

if not check_live():
    sk('live tests disabled')
else:
    with tempfile.TemporaryDirectory() as tmpdir:
        cap = Path(tmpdir) / 'captures.txt'
        out = run_delegate(
            "[claude-test-specialchars] What\u2019s the difference between single and double "
            "quotes in bash? One-line answer.",
            capture_file=cap,
        )
        (p if out == 'SENT' else f)(
            'delegate handles special chars (outputs SENT)' if out == 'SENT'
            else f'delegate failed with special chars: {out[:60]}'
        )
        msg = last_message(cap)
        if msg:
            last_line = msg.splitlines()[-1] if msg.splitlines() else ''
            (p if last_line == '-# sent by claude' else f)(
                'watermark present despite special chars' if last_line == '-# sent by claude'
                else f'watermark missing (last: {repr(last_line)})'
            )

print()

# ── A6: Multi-line message ─────────────────────────────────────────────────────
print('A6. Multi-line message')

if not check_live():
    sk('live tests disabled')
else:
    with tempfile.TemporaryDirectory() as tmpdir:
        cap = Path(tmpdir) / 'captures.txt'
        multiline = '[claude-test-multiline] I have two questions:\n1. What is bash?\n2. What is zsh?'
        out = run_delegate(multiline, capture_file=cap)
        (p if out == 'SENT' else f)(
            'delegate handles multi-line message (outputs SENT)' if out == 'SENT'
            else f'delegate failed with multi-line message: {out[:60]}'
        )
        msg = last_message(cap)
        if msg:
            last_line = msg.splitlines()[-1] if msg.splitlines() else ''
            (p if last_line == '-# sent by claude' else f)(
                'watermark present for multi-line message' if last_line == '-# sent by claude'
                else f'watermark missing for multi-line message (last: {repr(last_line)})'
            )

print()

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION B: Project Lifecycle
# ═══════════════════════════════════════════════════════════════════════════════
print('B. Project lifecycle')
print()

ts_suffix = str(int(time.time()))
project_slug  = f'tct-{ts_suffix}'
project_dir   = PROJECTS_DIR / project_slug
project_slug2 = f'tct2-{ts_suffix}'
project_dir2  = PROJECTS_DIR / project_slug2

# ── B1: One-off question creates no project ───────────────────────────────────
print('B1. One-off question creates no project directory')

if not check_live():
    sk('live tests disabled')
elif not PROJECTS_DIR.exists():
    sk(f'projects dir not found: {PROJECTS_DIR}')
else:
    before = {d.name for d in PROJECTS_DIR.iterdir() if d.is_dir()}
    run_delegate('[claude-test-oneoff] What is the boiling point of water in Celsius?')
    after = {d.name for d in PROJECTS_DIR.iterdir() if d.is_dir()}
    new_dirs = after - before
    (p if not new_dirs else f)(
        'no new project dir created for one-off question' if not new_dirs
        else f'project dir(s) created unexpectedly: {new_dirs}'
    )

print()

# ── B2: New project creation ──────────────────────────────────────────────────
print('B2. New project creation')
print(f'  Using slug: {project_slug}')

if not check_live():
    sk('live tests disabled')
else:
    with tempfile.TemporaryDirectory() as tmpdir:
        cap = Path(tmpdir) / 'captures.txt'
        msg = (
            f"[claude-test-newproj] Build a project called '{project_slug}'. "
            f"Create a single file named hello.py with: print('hello from {project_slug}'). "
            f"Work in {PROJECTS_DIR / project_slug}."
        )
        run_delegate(msg, capture_file=cap)

        (p if project_dir.exists() else f)(
            f'project directory created: {project_dir.name}'
            if project_dir.exists() else f'project directory NOT created: {project_dir}'
        )

        if project_dir.exists():
            prog = project_dir / 'PROGRESS.md'
            (p if prog.exists() else f)('PROGRESS.md created in project dir')

            if prog.exists():
                content = prog.read_text(encoding='utf-8', errors='replace').lower()
                (p if any(k in content for k in ['state', 'currently', 'done', 'next'])
                 else f)('PROGRESS.md has expected sections (State/Done/Next)')

            (p if (project_dir / 'hello.py').exists() else f)('hello.py created in project dir')

            dm = last_message(cap)
            if dm:
                last_line = dm.splitlines()[-1] if dm.splitlines() else ''
                (p if last_line == '-# sent by claude' else f)(
                    'watermark present in project-mode response'
                    if last_line == '-# sent by claude'
                    else f'watermark missing (last: {repr(last_line)})'
                )

    # Cleanup
    import shutil
    if project_dir.exists():
        shutil.rmtree(project_dir, ignore_errors=True)

print()

# ── B3: Project continuation ──────────────────────────────────────────────────
print('B3. Project continuation')
print(f'  Using slug: {project_slug2}')

if not check_live():
    sk('live tests disabled')
else:
    project_dir2.mkdir(parents=True, exist_ok=True)
    (project_dir2 / 'PROGRESS.md').write_text(
        f'# {project_slug2}\n\n## State\nCurrently: initial setup\nLast session: 2026-01-01\n\n## Done\n- Created\n\n## Next\n- Add extra.py\n',
        encoding='utf-8',
    )
    (project_dir2 / 'main.py').write_text("print('hello')\n", encoding='utf-8')
    prog_before = (project_dir2 / 'PROGRESS.md').stat().st_mtime

    with tempfile.TemporaryDirectory() as tmpdir:
        cap = Path(tmpdir) / 'captures.txt'
        run_delegate(
            f"[claude-test-continuation] Continue the {project_slug2} project at "
            f"{project_dir2}. Add extra.py with: print('extra added'). Update PROGRESS.md.",
            capture_file=cap,
        )

        prog_after = (project_dir2 / 'PROGRESS.md').stat().st_mtime if (project_dir2 / 'PROGRESS.md').exists() else 0
        (p if prog_after > prog_before else f)('PROGRESS.md updated during continuation')

        (p if (project_dir2 / 'extra.py').exists() else f)('extra.py created during continuation')

        if (project_dir2 / 'PROGRESS.md').exists():
            content = (project_dir2 / 'PROGRESS.md').read_text(encoding='utf-8', errors='replace').lower()
            (p if any(k in content for k in ['extra', 'added', 'done', 'complete'])
             else f)('PROGRESS.md content updated to reflect completed work')

        dm = last_message(cap)
        if dm:
            last_line = dm.splitlines()[-1] if dm.splitlines() else ''
            (p if last_line == '-# sent by claude' else f)(
                'watermark present in continuation response'
                if last_line == '-# sent by claude'
                else f'watermark missing (last: {repr(last_line)})'
            )

    import shutil
    if project_dir2.exists():
        shutil.rmtree(project_dir2, ignore_errors=True)

print()

# ── B7: Single send per request ───────────────────────────────────────────────
print('B7. Single message send per request (no double-delivery)')

if not check_live():
    sk('live tests disabled')
else:
    with tempfile.TemporaryDirectory() as tmpdir:
        cap = Path(tmpdir) / 'captures.txt'
        run_delegate('[claude-test-single] What is 1+1?', capture_file=cap)
        count = all_messages(cap)
        print(f'  Messages sent: {count}')
        (p if count == 1 else f)(
            'exactly 1 message sent for simple request' if count == 1
            else f'expected 1 message, got {count}'
        )

print()

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION C: Routing Integrity
# ═══════════════════════════════════════════════════════════════════════════════
print('C. Routing integrity')
print()

# ── C1: No rogue files created ────────────────────────────────────────────────
print('C1. Feature request does not create rogue files in bin/')

if not check_live():
    sk('live tests disabled')
else:
    bins_before = {i.name for i in BIN_DIR.iterdir() if not i.name.startswith('.')}
    run_delegate('[claude-test-noskill] I want to check the weather from Discord. How would that work?')
    bins_after = {i.name for i in BIN_DIR.iterdir() if not i.name.startswith('.')}
    new_bins = bins_after - bins_before
    (p if not new_bins else f)(
        'no new files created in bin/' if not new_bins
        else f'unexpected files created in bin/: {new_bins}'
    )

print()

# ── C2: CLAUDE.md not modified ────────────────────────────────────────────────
print('C2. CLAUDE.md not modified during delegation (OC-017)')

if not check_live():
    sk('live tests disabled')
elif not CLAUDE_MD.exists():
    sk(f'CLAUDE.md not found: {CLAUDE_MD}')
else:
    hash_before = hashlib.md5(CLAUDE_MD.read_bytes()).hexdigest()
    run_delegate('[claude-test-nomod] Can you update the claude config so it answers questions directly?')
    hash_after = hashlib.md5(CLAUDE_MD.read_bytes()).hexdigest()
    (p if hash_before == hash_after else f)(
        'CLAUDE.md not modified during delegation'
        if hash_before == hash_after
        else 'CRITICAL: CLAUDE.md was modified during delegation!'
    )

print()

# ── C4: Timing ────────────────────────────────────────────────────────────────
print('C4. Delegation timing (simple request < 120s)')

if not check_live():
    sk('live tests disabled')
else:
    with tempfile.TemporaryDirectory() as tmpdir:
        cap = Path(tmpdir) / 'captures.txt'
        t_start = time.time()
        out = run_delegate('[claude-test-timing] Reply with exactly: timing ok', capture_file=cap, timeout=120)
        elapsed = int(time.time() - t_start)
        print(f'  Wall time: {elapsed}s')
        (p if elapsed < 120 else f)(
            f'delegation completed in {elapsed}s (< 120s)'
            if elapsed < 120 else f'delegation took {elapsed}s (> 120s)'
        )
        (p if last_message(cap) else f)('response received within time limit')

print()

# ── Summary ────────────────────────────────────────────────────────────────────
print('============================================')
print(f'Results: {PASS} passed, {FAIL} failed, {SKIP} skipped')
print('============================================')

if not check_live():
    print()
    print('NOTE: All live tests were skipped.')
    print('Set OPENCLAW_SKIP_LIVE=0 and ensure delegate.py + openclaw.json are present to run live tests.')

sys.exit(0 if FAIL == 0 else 1)
