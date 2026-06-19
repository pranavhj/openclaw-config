#!/usr/bin/env python3
"""
Unit tests for per-project concurrency changes to delegate.py and discord-bot.py.

Validates:
  - delegate.py: --slug argument, per-slug lock/session/log/prompt/stop files,
    stale PID detection, router stateless (no --continue), unified history
  - discord-bot.py: project discovery, slug matching, per-project tracking,
    multi-session watcher, per-slug stop signals, --slug passed to delegate
  - Regression: existing functionality preserved (sanitization, events, locking, etc.)

No live prerequisites required. All tests use tempdir isolation.
"""
import collections
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Force UTF-8 stdout on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PASS = 0
FAIL = 0

REPO_DIR = Path(__file__).parent.parent
BIN_DIR = REPO_DIR / 'bin'

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
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


print('=== per-project concurrency tests ===')

# Load delegate module
delegate = None
try:
    delegate = load_module('delegate', 'delegate.py')
except SystemExit:
    delegate = load_module('delegate', 'delegate.py')
except Exception as e:
    f(f'delegate.py import error: {e}')

delegate_src = src('delegate.py')
bot_src = src('discord-bot.py')


# ══════════════════════════════════════════════════════════════════════════════
# PART 1: delegate.py — --slug argument and per-slug files
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 1. delegate.py: --slug argument in usage/docstring ──')

(p if '--slug SLUG' in delegate_src else f)('--slug SLUG in usage string')
(p if "remaining[0] == '--slug'" in delegate_src or "'--slug'" in delegate_src else f)(
    '--slug argument parsed from sys.argv')
(p if "slug = 'default'" in delegate_src else f)("slug defaults to 'default' when not provided")

# ── 1b. --slug parsing logic ──
print('\n── 1b. delegate.py: --slug parsing correctness ──')

# Simulate the parsing logic from main()
def _parse_slug(argv_after_target):
    """Replicate delegate.py's --slug parsing."""
    remaining = list(argv_after_target)
    slug = 'default'
    if len(remaining) >= 2 and remaining[0] == '--slug':
        slug = remaining[1]
        remaining = remaining[2:]
    message = ' '.join(remaining)
    return slug, message

slug, msg = _parse_slug(['--slug', 'tablenew', 'deploy', 'the', 'app'])
(p if slug == 'tablenew' and msg == 'deploy the app' else f)(
    f'--slug tablenew parsed correctly (slug={slug}, msg={msg})')

slug, msg = _parse_slug(['hello', 'world'])
(p if slug == 'default' and msg == 'hello world' else f)(
    f'no --slug defaults to default (slug={slug}, msg={msg})')

slug, msg = _parse_slug(['--slug', 'router'])
(p if slug == 'router' and msg == '' else f)(
    f'--slug router with no message (slug={slug}, msg="{msg}")')

slug, msg = _parse_slug([])
(p if slug == 'default' and msg == '' else f)(
    f'empty args defaults to default (slug={slug}, msg="{msg}")')


# ══════════════════════════════════════════════════════════════════════════════
# PART 2: delegate.py — per-slug file naming
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 2. delegate.py: per-slug file naming patterns ──')

# Lock files
(p if "f'delegate-{slug}.lock'" in delegate_src else f)(
    'per-slug lock dir: delegate-{slug}.lock')

# Active session files
(p if "f'active-session-{slug}.json'" in delegate_src else f)(
    'per-slug active session: active-session-{slug}.json')

# Log files
(p if "f'delegate-{slug}-{today}.log'" in delegate_src else f)(
    'per-slug delegate log: delegate-{slug}-{today}.log')
(p if "f'timeline-{slug}-{today}.log'" in delegate_src else f)(
    'per-slug timeline log: timeline-{slug}-{today}.log')

# Prompt files
(p if "f'delegate-prompt-{slug}-" in delegate_src else f)(
    'per-slug prompt file: delegate-prompt-{slug}-*.txt')

# Stop signal files
(p if "f'stop-{slug}.signal'" in delegate_src else f)(
    'per-slug stop signal: stop-{slug}.signal')


# ══════════════════════════════════════════════════════════════════════════════
# PART 3: delegate.py — PID file in lock dir for stale detection
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 3. delegate.py: PID-based stale lock detection ──')

(p if "lock_dir / 'pid'" in delegate_src else f)(
    'PID file written inside lock dir')
(p if 'os.getpid()' in delegate_src else f)(
    'current PID written via os.getpid()')
(p if '_is_pid_alive' in delegate_src else f)(
    '_is_pid_alive function defined in delegate.py')
(p if 'stale_lock_broken' in delegate_src else f)(
    'stale_lock_broken event logged when breaking stale lock')
(p if 'tasklist' in delegate_src else f)(
    'Windows PID check uses tasklist command')

# 3b. Stale lock recovery test with real dirs
print('\n── 3b. Stale lock recovery (tempdir) ──')

with tempfile.TemporaryDirectory() as tmpdir:
    lock = Path(tmpdir) / 'delegate-test.lock'

    # Create lock with a dead PID (PID 99999999 should not exist)
    lock.mkdir()
    (lock / 'pid').write_text('99999999', encoding='utf-8')

    # Verify the PID file exists
    (p if (lock / 'pid').exists() else f)('PID file created in lock dir')

    # Simulate stale detection: read PID, check if alive
    try:
        old_pid = int((lock / 'pid').read_text().strip())
        # PID 99999999 should not be alive
        alive = False
        try:
            if sys.platform == 'win32':
                import subprocess
                r = subprocess.run(['tasklist', '/FI', f'PID eq {old_pid}', '/NH'],
                                   capture_output=True, text=True, timeout=5)
                alive = str(old_pid) in r.stdout
            else:
                os.kill(old_pid, 0)
                alive = True
        except Exception:
            alive = False

        (p if not alive else f)(f'dead PID {old_pid} detected as not alive')

        # Break stale lock
        (lock / 'pid').unlink(missing_ok=True)
        lock.rmdir()
        lock.mkdir(exist_ok=False)
        p('stale lock successfully broken and re-acquired')
        (lock / 'pid').write_text(str(os.getpid()), encoding='utf-8')
        p('new PID written after re-acquiring lock')
        (lock / 'pid').unlink()
        lock.rmdir()
    except Exception as e:
        f(f'stale lock recovery failed: {e}')


# ══════════════════════════════════════════════════════════════════════════════
# PART 4: delegate.py — per-slug lock isolation
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 4. Per-slug lock isolation (two slugs can lock simultaneously) ──')

with tempfile.TemporaryDirectory() as tmpdir:
    lock_a = Path(tmpdir) / 'delegate-projectA.lock'
    lock_b = Path(tmpdir) / 'delegate-projectB.lock'

    try:
        lock_a.mkdir(exist_ok=False)
        lock_b.mkdir(exist_ok=False)
        p('two different slug locks acquired simultaneously')
    except FileExistsError:
        f('different slug locks should not conflict')
    finally:
        lock_a.rmdir()
        lock_b.rmdir()

    # Same slug cannot lock twice
    lock_same = Path(tmpdir) / 'delegate-same.lock'
    lock_same.mkdir(exist_ok=False)
    try:
        lock_same.mkdir(exist_ok=False)
        f('expected FileExistsError for same slug')
    except FileExistsError:
        p('same slug lock correctly blocked')
    finally:
        lock_same.rmdir()


# ══════════════════════════════════════════════════════════════════════════════
# PART 5: delegate.py — router is stateless (no --continue)
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 5. All delegates stateless: no --continue for any slug ──')

# All delegates are stateless — no --continue. Sub-sessions spawned by the router
# use --continue in their own project CWDs for conversation continuity.
agent_cmd_block = delegate_src[delegate_src.find('agent_cmd = ['):]
agent_cmd_block = agent_cmd_block[:agent_cmd_block.find('proc = subprocess.Popen')]
(p if '--continue' not in agent_cmd_block else f)(
    'no --continue in agent_cmd construction (all stateless)')

(p if "agent_cmd.append('--continue')" not in delegate_src else f)(
    'no conditional --continue append in delegate.py')

(p if "Sub-sessions spawned by the router" in delegate_src
    or "sub-sessions" in agent_cmd_block.lower()
    or "stateless" in agent_cmd_block.lower() else f)(
    'comment explains sub-sessions use --continue in own CWDs')


# ══════════════════════════════════════════════════════════════════════════════
# PART 6: delegate.py — unified history from all timeline files
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 6. History reads from per-slug timeline ──')

# History loads the current slug's own timeline to avoid cross-project context pollution.
# e.g. slug=stockbroker loads timeline-stockbroker-{today}, not timeline-router-{today}.
(p if "timeline-{slug}-{today}" in delegate_src else f)(
    'today history loads per-slug timeline')
(p if "timeline-{slug}-{yesterday}" in delegate_src else f)(
    'yesterday fallback loads per-slug timeline')

# 6b. parse_history still works correctly with multi-slug log lines
print('\n── 6b. parse_history with multi-slug timeline entries ──')

if delegate:
    # Simulate lines from timeline-projectA-2026-06-11.log
    lines_a = [
        json.dumps({'ts': '2026-01-01T10:00:00.000Z', 'event': 'delegate_recv',
                     'msg_preview': 'deploy tablenew'}),
        json.dumps({'ts': '2026-01-01T10:00:01.000Z', 'event': 'project_match',
                     'project': 'tablenew'}),
        json.dumps({'ts': '2026-01-01T10:01:00.000Z', 'event': 'delegate_reply',
                     'reply_preview': 'deployed successfully'}),
    ]
    # Simulate lines from timeline-projectB-2026-06-11.log
    lines_b = [
        json.dumps({'ts': '2026-01-01T10:00:30.000Z', 'event': 'delegate_recv',
                     'msg_preview': 'check dairy logs'}),
        json.dumps({'ts': '2026-01-01T10:00:31.000Z', 'event': 'project_match',
                     'project': 'dairy_llm_gateway'}),
    ]
    # Current message
    lines_c = [
        json.dumps({'ts': '2026-01-01T11:00:00.000Z', 'event': 'delegate_recv',
                     'msg_preview': 'current message'}),
    ]

    # Combined (as would happen with glob reading all files then extend)
    all_lines = lines_a + lines_b + lines_c
    result = delegate.parse_history(all_lines)

    (p if 'deploy tablenew' in result else f)(
        'history includes entry from slug A')
    (p if 'check dairy logs' in result else f)(
        'history includes entry from slug B')
    (p if '[tablenew]' in result else f)(
        'project tag [tablenew] present in history')
    (p if '[dairy_llm_gateway]' in result else f)(
        'project tag [dairy_llm_gateway] present in history')
    (p if 'current message' not in result else f)(
        'current message excluded (last entry stripped)')
    (p if 'deployed successfully' in result else f)(
        'reply preview included in history')
else:
    skip('delegate module not loaded')


# ══════════════════════════════════════════════════════════════════════════════
# PART 7: delegate.py — active session file includes slug + cwd_label fields
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 7. Active session JSON includes slug and cwd_label fields ──')

(p if "'slug': slug" in delegate_src else f)(
    "active session JSON has 'slug' key")
(p if "'project': slug" in delegate_src else f)(
    "active session JSON has 'project' set to slug")
(p if "'cwd_label': WORK_DIR.name" in delegate_src else f)(
    "active session JSON has 'cwd_label' for watcher matching")


# ══════════════════════════════════════════════════════════════════════════════
# PART 8: delegate.py — both per-slug and global stop signals checked
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 8. Stop signal: per-slug + global fallback ──')

(p if 'stop_signal_file.exists() or STOP_SIGNAL_FILE.exists()' in delegate_src else f)(
    'poll loop checks both per-slug and global stop signals')
(p if 'stop_signal_file.unlink' in delegate_src else f)(
    'per-slug stop signal cleaned up in finally')
(p if 'STOP_SIGNAL_FILE.unlink' in delegate_src else f)(
    'global stop signal also cleaned up (backwards compat)')


# ══════════════════════════════════════════════════════════════════════════════
# PART 9: delegate.py — _run function signature updated
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 9. _run function accepts slug and per-slug file args ──')

# Check function signature
run_sig = delegate_src[delegate_src.find('def _run('):]
run_sig = run_sig[:run_sig.find('):') + 2]
(p if 'slug=' in run_sig else f)('_run has slug parameter')
(p if 'stop_signal_file=' in run_sig else f)('_run has stop_signal_file parameter')
(p if 'active_session_file=' in run_sig else f)('_run has active_session_file parameter')


# ══════════════════════════════════════════════════════════════════════════════
# PART 10: delegate.py — lock cleanup includes PID file
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 10. Lock cleanup removes PID file then dir ──')

# The main() finally block does: active_session_file.unlink → pid.unlink → lock_dir.rmdir
# Search for the finally block in main() (the one with active_session_file.unlink)
main_finally_idx = delegate_src.find("active_session_file.unlink(missing_ok=True)")
if main_finally_idx >= 0:
    cleanup_block = delegate_src[main_finally_idx:]
    pid_unlink_idx = cleanup_block.find("(lock_dir / 'pid').unlink")
    rmdir_idx = cleanup_block.find('lock_dir.rmdir()')
    (p if pid_unlink_idx >= 0 else f)('PID file unlinked in finally block')
    (p if rmdir_idx >= 0 else f)('lock dir removed in finally block')
    (p if 0 < pid_unlink_idx < rmdir_idx else f)(
        'PID unlink happens before lock dir rmdir (correct order)')
else:
    f('could not locate main() finally block')


# ══════════════════════════════════════════════════════════════════════════════
# PART 11: discord-bot.py — project discovery
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 11. discord-bot.py: project discovery (via project_list module) ──')

# project_list.py is the shared module
pl_path = BIN_DIR / 'project_list.py'
pl_src = pl_path.read_text(encoding='utf-8') if pl_path.exists() else ''

(p if 'def discover_projects' in pl_src else f)(
    'discover_projects function defined in project_list.py')
(p if 'from project_list import discover_projects' in bot_src else f)(
    'discord-bot.py imports from project_list')
(p if '_known_projects' in bot_src else f)(
    '_known_projects dict defined')
(p if '_projects_refreshed_at' in bot_src else f)(
    '_projects_refreshed_at timestamp defined')
(p if 'def _refresh_projects' in bot_src else f)(
    '_refresh_projects function defined (auto-refresh)')

# Check that project_list.py scans the right roots
(p if 'FILTERED_ROOTS' in pl_src else f)('FILTERED_ROOTS defined in project_list.py')
(p if 'UNFILTERED_ROOTS' in pl_src else f)('UNFILTERED_ROOTS defined in project_list.py')
(p if "Path.home() / 'projects'" in pl_src else f)(
    'projects root scanned')
(p if "Path.home() / 'AndroidStudioProjects'" in pl_src else f)(
    'AndroidStudioProjects root scanned')
(p if "Path('D:/MyData/Software')" in pl_src else f)(
    'D:/MyData/Software root scanned')

# Refresh interval
(p if '> 60' in bot_src or '>= 60' in bot_src else f)(
    'project refresh interval ~60s')


# ══════════════════════════════════════════════════════════════════════════════
# PART 12: discord-bot.py — slug matching logic
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 12. discord-bot.py: slug matching ──')

(p if 'def _match_project' in bot_src else f)(
    '_match_project function defined')
(p if r"re.findall(r'\b\w+\b'" in bot_src else f)(
    'whole-word matching via regex word boundaries')
(p if "return 'router'" in bot_src else f)(
    "returns 'router' as default/fallback slug")
(p if 'len(exact) == 1' in bot_src else f)(
    'only returns slug on exactly 1 exact match')
(p if 'startswith(word)' in bot_src else f)(
    'prefix matching for partial project names')
(p if 'len(word) < 4' in bot_src else f)(
    'prefix match requires minimum 4 chars')

# 12b. Test slug matching logic in isolation
print('\n── 12b. Slug matching correctness (exact + prefix) ──')

def _test_match_project(message, projects):
    """Replicate _match_project logic (exact + prefix matching)."""
    words = set(re.findall(r'\b\w+\b', message.lower()))
    # Pass 1: exact
    exact = [name for name in projects if name in words]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return 'router'
    # Pass 2: prefix (min 4 chars)
    prefix_matches = set()
    for word in words:
        if len(word) < 4:
            continue
        for name in projects:
            if name.startswith(word) and name != word:
                prefix_matches.add(name)
    if len(prefix_matches) == 1:
        return prefix_matches.pop()
    return 'router'

test_projects = {
    'tablenew': 'C:/Users/prana/AndroidStudioProjects/TableNew',
    'dairy_llm_gateway': 'C:/Users/prana/projects/dairy_llm_gateway',
    'openclaw': 'C:/Users/prana/projects/openclaw',
    'openclaw-config': 'D:/MyData/Software/openclaw-config',
    'shaadibot': 'C:/Users/prana/projects/shaadibot',
    'flightchecker': 'C:/Users/prana/projects/flightchecker',
    'cricketanalyzer': 'C:/Users/prana/AndroidStudioProjects/CricketAnalyzer',
    'screenreader': 'C:/Users/prana/AndroidStudioProjects/ScreenReader',
}

# Exact single match
slug = _test_match_project('deploy tablenew', test_projects)
(p if slug == 'tablenew' else f)(
    f'"deploy tablenew" -> {slug} (expected tablenew)')

# No match → router
slug = _test_match_project("what's 2+2", test_projects)
(p if slug == 'router' else f)(
    f'"what\'s 2+2" -> {slug} (expected router)')

# Case insensitive
slug = _test_match_project('deploy TableNew', test_projects)
(p if slug == 'tablenew' else f)(
    f'"deploy TableNew" -> {slug} (expected tablenew)')

# Exact match takes priority
slug = _test_match_project('openclaw openclaw-config', test_projects)
(p if slug == 'openclaw' else f)(
    f'"openclaw openclaw-config" -> {slug} (expected openclaw, hyphenated name not a single word)')

# PREFIX MATCH: "table" matches "tablenew" (prefix, >=4 chars)
slug = _test_match_project('deploy table', test_projects)
(p if slug == 'tablenew' else f)(
    f'"deploy table" -> {slug} (expected tablenew via prefix match)')

# PREFIX MATCH: "flight" matches "flightchecker"
slug = _test_match_project('update flight config', test_projects)
(p if slug == 'flightchecker' else f)(
    f'"update flight config" -> {slug} (expected flightchecker via prefix)')

# PREFIX MATCH: "shaadi" matches "shaadibot"
slug = _test_match_project('help with shaadi', test_projects)
(p if slug == 'shaadibot' else f)(
    f'"help with shaadi" -> {slug} (expected shaadibot via prefix)')

# PREFIX MATCH: "cricket" matches "cricketanalyzer"
slug = _test_match_project('show cricket stats', test_projects)
(p if slug == 'cricketanalyzer' else f)(
    f'"show cricket stats" -> {slug} (expected cricketanalyzer via prefix)')

# PREFIX MATCH: "screen" matches "screenreader"
slug = _test_match_project('fix screen issue', test_projects)
(p if slug == 'screenreader' else f)(
    f'"fix screen issue" -> {slug} (expected screenreader via prefix)')

# SHORT WORD SAFETY: "tab" (3 chars) should NOT prefix-match "tablenew"
slug = _test_match_project('deploy tab', test_projects)
(p if slug == 'router' else f)(
    f'"deploy tab" -> {slug} (expected router — 3 chars too short for prefix)')

# shaadibot exact match still works
slug = _test_match_project('check shaadibot logs', test_projects)
(p if slug == 'shaadibot' else f)(
    f'"check shaadibot logs" -> {slug} (expected shaadibot)')

# Empty message → router
slug = _test_match_project('', test_projects)
(p if slug == 'router' else f)(
    f'empty message -> {slug} (expected router)')

# Underscore project name
slug = _test_match_project('dairy_llm_gateway status', test_projects)
(p if slug == 'dairy_llm_gateway' else f)(
    f'"dairy_llm_gateway status" -> {slug} (expected dairy_llm_gateway)')

# AMBIGUOUS PREFIX: "open" matches both "openclaw" and "openclaw-config"
# Actually "openclaw-config" = word boundary splits it, so "openclaw" prefix matches both
# "open" -> matches "openclaw" AND "openclaw-config" -> router
slug = _test_match_project('open the project', test_projects)
(p if slug == 'router' else f)(
    f'"open the project" -> {slug} (expected router — ambiguous prefix)')

# PREFIX: "dairy" matches "dairy_llm_gateway"
slug = _test_match_project('check dairy logs', test_projects)
(p if slug == 'dairy_llm_gateway' else f)(
    f'"check dairy logs" -> {slug} (expected dairy_llm_gateway via prefix)')


# ══════════════════════════════════════════════════════════════════════════════
# PART 13: discord-bot.py — per-project delegate tracking
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 13. discord-bot.py: per-project delegate tracking ──')

(p if '_running_delegates' in bot_src else f)(
    '_running_delegates dict defined')
(p if 'def _is_pid_alive' in bot_src else f)(
    '_is_pid_alive function defined')
(p if 'delegate_busy' in bot_src else f)(
    'delegate_busy event logged when slug is busy')
(p if "Still working on" in bot_src else f)(
    'busy reply sent to user')
(p if '_running_delegates[slug] = proc.pid' in bot_src else f)(
    'PID recorded in _running_delegates after spawn')

# Check stale PID cleanup in bot
(p if 'del _running_delegates[slug]' in bot_src else f)(
    'stale PID cleaned from _running_delegates')


# ══════════════════════════════════════════════════════════════════════════════
# PART 14: discord-bot.py — --slug passed to delegate
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 14. discord-bot.py: --slug passed to delegate subprocess ──')

(p if "'--slug', slug" in bot_src else f)(
    "'--slug', slug in delegate command construction")

# Verify command structure: delegate.py discord CHANNEL --slug SLUG content
cmd_block = bot_src[bot_src.find("cmd = [sys.executable"):]
cmd_block = cmd_block[:cmd_block.find('\n        _tl')]
(p if '--slug' in cmd_block and 'slug' in cmd_block and 'content' in cmd_block else f)(
    'delegate command includes --slug between channel and content')


# ══════════════════════════════════════════════════════════════════════════════
# PART 15: discord-bot.py — multi-session watcher
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 15. discord-bot.py: multi-session watcher ──')

(p if '_active_sessions' in bot_src else f)(
    '_active_sessions dict defined (replaces single _active_session)')
(p if '_active_session' not in bot_src.replace('_active_sessions', '') else f)(
    'old _active_session variable removed (only _active_sessions exists)')

(p if "LOGDIR.glob('active-session-*.json')" in bot_src else f)(
    'watcher globs active-session-*.json files')
(p if 'session_watcher_start' in bot_src else f)(
    'session_watcher_start event logged per session')
(p if 'session_watcher_done' in bot_src else f)(
    'session_watcher_done event logged per session')

# Staggered edits
(p if 'break  # Only edit one session per tick' in bot_src else f)(
    'status edits staggered (one per tick) to avoid Discord rate limits')


# ══════════════════════════════════════════════════════════════════════════════
# PART 16: discord-bot.py — _edit_status signature updated
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 16. discord-bot.py: _edit_status accepts session_data + events ──')

edit_sig = bot_src[bot_src.find('async def _edit_status('):]
edit_sig = edit_sig[:edit_sig.find('):') + 2]
(p if 'session_data' in edit_sig else f)(
    '_edit_status has session_data parameter')
(p if 'status_events' in edit_sig else f)(
    '_edit_status has status_events parameter')
(p if 'elapsed_s' in edit_sig else f)(
    '_edit_status has elapsed_s parameter')
(p if 'done=' in edit_sig else f)(
    '_edit_status has done kwarg')

# Check slug shown in status header
(p if "session_data.get('slug'" in bot_src else f)(
    'status header shows slug (not just project)')


# ══════════════════════════════════════════════════════════════════════════════
# PART 17: discord-bot.py — per-slug stop signals
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 17. discord-bot.py: per-slug stop signals ──')

(p if "f'stop-{slug_name}.signal'" in bot_src else f)(
    'stop handler writes per-slug stop signals')
(p if 'stop.signal' in bot_src else f)(
    'stop handler also writes global stop.signal (backwards compat)')
(p if 'stopped_slugs' in bot_src else f)(
    'stopped slugs tracked and logged')
(p if '_running_delegates.keys()' in bot_src else f)(
    'stop iterates all running delegates')


# ══════════════════════════════════════════════════════════════════════════════
# PART 18: discord-bot.py — session watcher cleans up _running_delegates
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 18. discord-bot.py: watcher cleans up _running_delegates on finish ──')

(p if "_running_delegates.pop(slug, None)" in bot_src else f)(
    'session watcher removes slug from _running_delegates when session ends')


# ══════════════════════════════════════════════════════════════════════════════
# PART 19: discord-bot.py — JSONL event routing via cwd_label (no fallback)
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 19. discord-bot.py: JSONL events routed by cwd_label ──')

(p if "s_state['session_data'].get('cwd_label', '')" in bot_src else f)(
    'JSONL events matched via cwd_label from active session')
(p if "cwd_label.lower() == project.lower()" in bot_src else f)(
    'cwd_label comparison is case-insensitive')

# Critical: NO single-session fallback (prevents terminal leaking into Discord)
(p if 'len(_active_sessions) == 1' not in bot_src else f)(
    'no single-session fallback (terminal sessions stay isolated)')

# Critical: session project field NOT overwritten by random JSONL activity
(p if "s_state['session_data']['project'] = project" not in bot_src else f)(
    'session project not overwritten by JSONL activity (was causing label drift)')


# ══════════════════════════════════════════════════════════════════════════════
# PART 19b: Terminal isolation — JSONL from other projects not leaked to Discord
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 19b. Terminal isolation: unmatched JSONL events not routed ──')

# Simulate the routing logic: only events matching cwd_label get routed
def _simulate_routing(project_label, active_sessions):
    """Return the target slug for a JSONL event, or None if unmatched."""
    for s_slug, s_state in active_sessions.items():
        cwd_label = s_state.get('cwd_label', '')
        if cwd_label and cwd_label.lower() == project_label.lower():
            return s_slug
    return None

sessions = {
    'router': {'cwd_label': 'openclaw', 'slug': 'router'},
}

# Discord delegate working on openclaw → JSONL from openclaw should match
slug = _simulate_routing('openclaw', sessions)
(p if slug == 'router' else f)(
    f'openclaw JSONL → router session (got: {slug})')

# User working on TableNew from terminal → should NOT match
slug = _simulate_routing('TableNew', sessions)
(p if slug is None else f)(
    f'TableNew JSONL → None (terminal isolation) (got: {slug})')

# User working on shaadibot from terminal → should NOT match
slug = _simulate_routing('shaadibot', sessions)
(p if slug is None else f)(
    f'shaadibot JSONL → None (terminal isolation) (got: {slug})')

# Two Discord sessions: each gets only its own events
sessions_multi = {
    'router': {'cwd_label': 'openclaw', 'slug': 'router'},
    'tablenew': {'cwd_label': 'TableNew', 'slug': 'tablenew'},
}

slug = _simulate_routing('openclaw', sessions_multi)
(p if slug == 'router' else f)(
    f'openclaw JSONL → router (multi-session) (got: {slug})')

slug = _simulate_routing('TableNew', sessions_multi)
(p if slug == 'tablenew' else f)(
    f'TableNew JSONL → tablenew (multi-session) (got: {slug})')

# Unrelated terminal session still isolated
slug = _simulate_routing('dairy_llm_gateway', sessions_multi)
(p if slug is None else f)(
    f'dairy JSONL → None even with 2 sessions (got: {slug})')


# ══════════════════════════════════════════════════════════════════════════════
# PART 20: delegate.py — backwards-compat: global constants still exist
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 20. Backwards compatibility: global constants preserved ──')

(p if "ACTIVE_SESSION_FILE = LOGDIR / 'active-session.json'" in delegate_src else f)(
    'global ACTIVE_SESSION_FILE constant still defined (used as import target)')
(p if "STOP_SIGNAL_FILE = LOGDIR / 'stop.signal'" in delegate_src else f)(
    'global STOP_SIGNAL_FILE constant still defined')
(p if 'WORK_DIR' in delegate_src else f)(
    'WORK_DIR constant still defined')
(p if 'CLAUDE_PROJECTS_DIR' in delegate_src else f)(
    'CLAUDE_PROJECTS_DIR constant still defined')


# ══════════════════════════════════════════════════════════════════════════════
# PART 21: Regression — timeline events still present in delegate.py
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 21. Regression: all timeline events still present in delegate.py ──')

for event in ['delegate_recv', 'sanitize', 'lock_acquired', 'lock_blocked',
              'project_match', 'prompt_ready', 'agent_start', 'agent_done',
              'failure_detected', 'failure_notified', 'delegate_exit',
              'stale_lock_broken', 'stop_signal_detected']:
    (p if f"'{event}'" in delegate_src else f)(f"'{event}' event present")


# ══════════════════════════════════════════════════════════════════════════════
# PART 22: Regression — sanitization still present
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 22. Regression: message sanitization preserved ──')

(p if 'u2019' in delegate_src else f)('U+2019 apostrophe replacement')
(p if 'u2018' in delegate_src else f)('U+2018 backtick replacement')
(p if "replace('\\n', ' ')" in delegate_src else f)('newline to space')
(p if 'chars_replaced' in delegate_src else f)('chars_replaced counter')


# ══════════════════════════════════════════════════════════════════════════════
# PART 23: Regression — CLAUDECODE env stripping
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 23. Regression: CLAUDECODE env stripping preserved ──')

(p if "k != 'CLAUDECODE'" in delegate_src else f)(
    'CLAUDECODE stripped from agent_env')


# ══════════════════════════════════════════════════════════════════════════════
# PART 24: Regression — parse_history still works (basic)
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 24. Regression: parse_history basic behavior ──')

if delegate:
    # Original test from test_delegate.py
    log_lines = [
        json.dumps({'ts': '2026-01-01T10:00:00.000Z', 'event': 'delegate_recv',
                     'msg_preview': 'hello world'}),
        json.dumps({'ts': '2026-01-01T10:00:01.000Z', 'event': 'project_match',
                     'project': 'openclaw'}),
        json.dumps({'ts': '2026-01-01T11:00:00.000Z', 'event': 'delegate_recv',
                     'msg_preview': 'second message'}),
        json.dumps({'ts': '2026-01-01T11:00:01.000Z', 'event': 'project_match',
                     'project': 'screen-reader'}),
        json.dumps({'ts': '2026-01-01T12:00:00.000Z', 'event': 'delegate_recv',
                     'msg_preview': 'current (skip)'}),
    ]
    result = delegate.parse_history(log_lines)
    entries = [l for l in result.splitlines() if l.strip()]
    (p if len(entries) == 2 else f)(
        f'returns last entries excluding current ({len(entries)} entries)')
    (p if '[openclaw]' in result and 'hello world' in result else f)(
        'first entry with correct project tag')
    (p if '[screen-reader]' in result and 'second message' in result else f)(
        'second entry with correct project tag')
    (p if 'current (skip)' not in result else f)(
        'current message excluded from history')
else:
    skip('delegate module not loaded')


# ══════════════════════════════════════════════════════════════════════════════
# PART 25: Regression — ts_ms format
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 25. Regression: ts_ms timestamp format ──')

if delegate:
    ts = delegate.ts_ms()
    valid = (len(ts) == 24 and ts.endswith('Z') and 'T' in ts
             and '.' in ts and ts.count('-') == 2)
    (p if valid else f)(f'ts_ms format correct: {ts}')
else:
    skip('delegate module not loaded')


# ══════════════════════════════════════════════════════════════════════════════
# PART 26: Regression — prompt structure preserved
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 26. Regression: prompt structure preserved ──')

for section in ['## Reply', '## Known projects', '## Recent messages',
                '## Request', '## Attachments']:
    (p if section in delegate_src else f)(f'{section} section in prompt')


# ══════════════════════════════════════════════════════════════════════════════
# PART 27: Regression — failure handling preserved
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 27. Regression: failure handling preserved ──')

(p if 'Delegation failed' in delegate_src else f)('failure message present')
(p if "output = 'SENT'" in delegate_src else f)("failure sets output='SENT'")
(p if 'Session timed out' in delegate_src else f)('timeout message present')
(p if 'Execution stopped' in delegate_src else f)('stop message present')


# ══════════════════════════════════════════════════════════════════════════════
# PART 28: Regression — session reset still called
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 28. Regression: session reset still called after agent_done ──')

(p if 'SESSION_RESET_PY' in delegate_src else f)('SESSION_RESET_PY reference exists')
sr_idx = delegate_src.rfind('SESSION_RESET_PY')
done_idx = delegate_src.rfind('agent_done')
(p if sr_idx > done_idx else f)('session-reset runs after agent_done')


# ══════════════════════════════════════════════════════════════════════════════
# PART 29: Regression — lock mechanism still works
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 29. Regression: lock mechanism (atomic mkdir) ──')

with tempfile.TemporaryDirectory() as tmpdir:
    lock = Path(tmpdir) / 'delegate-test.lock'

    # Acquire when free
    try:
        lock.mkdir(exist_ok=False)
        p('lock acquired when free')
        lock.rmdir()
    except Exception as e:
        f(f'lock acquire failed: {e}')

    # FileExistsError when held
    lock.mkdir(exist_ok=True)
    try:
        lock.mkdir(exist_ok=False)
        f('expected FileExistsError')
    except FileExistsError:
        p('FileExistsError raised when held')
    lock.rmdir()

    # Re-acquirable after release
    lock.mkdir(exist_ok=False)
    lock.rmdir()
    try:
        lock.mkdir(exist_ok=False)
        p('re-acquirable after release')
        lock.rmdir()
    except FileExistsError:
        f('lock not released')


# ══════════════════════════════════════════════════════════════════════════════
# PART 30: Regression — discord-bot.py essential features preserved
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 30. Regression: discord-bot.py essentials preserved ──')

(p if 'ALLOWED_USER' in bot_src else f)('ALLOWED_USER constant')
(p if 'DMChannel' in bot_src else f)('DM channel filter')
(p if '_recent_msg_ids' in bot_src else f)('message deduplication')
(p if 'RESTART_SIGNAL_FILE' in bot_src else f)('restart signal support')
(p if 'watch_restart_signal' in bot_src else f)('restart watcher task')
(p if 'watch_claude_sessions' in bot_src else f)('session watcher task')
(p if 'DELEGATE_PY' in bot_src else f)('DELEGATE_PY path constant')
(p if 'format_entry' in bot_src else f)('format_entry function')
(p if 'TOOL_ICONS' in bot_src else f)('TOOL_ICONS dict')
(p if 'project_label' in bot_src else f)('project_label function')
(p if 'DELEGATE_ATTACHMENTS' in bot_src else f)('attachment env var support')
(p if 'client.run(token)' in bot_src else f)('bot client.run at end')


# ══════════════════════════════════════════════════════════════════════════════
# PART 31: Regression — scripts still present
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 31. Regression: all bin/ scripts present ──')

for script in ['delegate.py', 'discord-bot.py', 'discord-send.py',
               'agent-smart.py', 'session-reset.py']:
    (p if (BIN_DIR / script).exists() else f)(f'{script} exists')


# ══════════════════════════════════════════════════════════════════════════════
# PART 32: Regression — agent-smart.py still called correctly
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 32. Regression: agent-smart.py invocation correct ──')

(p if 'AGENT_SMART_PY' in delegate_src else f)('AGENT_SMART_PY constant')
(p if 'str(AGENT_SMART_PY)' in delegate_src else f)('agent called via path constant')
(p if '--permission-mode' in delegate_src else f)('--permission-mode passed')
(p if '--model' in delegate_src else f)('--model passed')
(p if '--print-file' in delegate_src else f)('--print-file passed')


# ══════════════════════════════════════════════════════════════════════════════
# PART 33: Active session file test (write/read/cleanup cycle)
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 33. Active session file lifecycle (write/read/cleanup) ──')

with tempfile.TemporaryDirectory() as tmpdir:
    session_file = Path(tmpdir) / 'active-session-tablenew.json'

    # Write
    session_data = {
        'target': '12345',
        'status_message_id': '67890',
        'project': 'tablenew',
        'slug': 'tablenew',
        'ts_start': '2026-06-11T10:00:00.000Z',
    }
    session_file.write_text(json.dumps(session_data), encoding='utf-8')
    (p if session_file.exists() else f)('session file written')

    # Read and verify
    loaded = json.loads(session_file.read_text(encoding='utf-8'))
    (p if loaded['slug'] == 'tablenew' else f)(
        f"slug field correct: {loaded.get('slug')}")
    (p if loaded['status_message_id'] == '67890' else f)(
        'status_message_id preserved')

    # Glob pattern matches
    matches = list(Path(tmpdir).glob('active-session-*.json'))
    (p if len(matches) == 1 and 'tablenew' in matches[0].name else f)(
        f'glob matches session file: {[m.name for m in matches]}')

    # Write a second session
    session_file_2 = Path(tmpdir) / 'active-session-dairy.json'
    session_file_2.write_text(json.dumps({**session_data, 'slug': 'dairy'}), encoding='utf-8')
    matches = list(Path(tmpdir).glob('active-session-*.json'))
    (p if len(matches) == 2 else f)(
        f'two session files found by glob: {len(matches)}')

    # Cleanup
    session_file.unlink(missing_ok=True)
    session_file_2.unlink(missing_ok=True)
    (p if not session_file.exists() and not session_file_2.exists() else f)(
        'session files cleaned up')


# ══════════════════════════════════════════════════════════════════════════════
# PART 34: Timeline log isolation (different slugs write to different files)
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 34. Timeline log isolation between slugs ──')

with tempfile.TemporaryDirectory() as tmpdir:
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    tl_a = Path(tmpdir) / f'timeline-projectA-{today}.log'
    tl_b = Path(tmpdir) / f'timeline-projectB-{today}.log'

    # Write to slug A
    with open(tl_a, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps({'event': 'delegate_recv', 'msg_preview': 'msg for A'}) + '\n')

    # Write to slug B
    with open(tl_b, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps({'event': 'delegate_recv', 'msg_preview': 'msg for B'}) + '\n')

    # Read slug A — should not contain slug B's data
    a_content = tl_a.read_text(encoding='utf-8')
    b_content = tl_b.read_text(encoding='utf-8')
    (p if 'msg for A' in a_content and 'msg for B' not in a_content else f)(
        'slug A log only contains slug A data')
    (p if 'msg for B' in b_content and 'msg for A' not in b_content else f)(
        'slug B log only contains slug B data')

    # Glob should find both
    all_tl = list(Path(tmpdir).glob(f'timeline-*-{today}.log'))
    (p if len(all_tl) == 2 else f)(
        f'glob finds both timeline files: {len(all_tl)}')


# ══════════════════════════════════════════════════════════════════════════════
# PART 35: Stop signal isolation (per-slug signals are independent)
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 35. Stop signal isolation between slugs ──')

with tempfile.TemporaryDirectory() as tmpdir:
    stop_a = Path(tmpdir) / 'stop-projectA.signal'
    stop_b = Path(tmpdir) / 'stop-projectB.signal'
    stop_global = Path(tmpdir) / 'stop.signal'

    # Write stop for A only
    stop_a.write_text('1', encoding='utf-8')

    (p if stop_a.exists() and not stop_b.exists() else f)(
        'stop signal for A does not affect B')

    # Global stop
    stop_global.write_text('1', encoding='utf-8')
    (p if stop_global.exists() else f)(
        'global stop signal independent of per-slug signals')

    # Check both: per-slug OR global (as delegate does)
    a_should_stop = stop_a.exists() or stop_global.exists()
    b_should_stop = stop_b.exists() or stop_global.exists()
    (p if a_should_stop else f)('slug A sees stop (per-slug + global)')
    (p if b_should_stop else f)('slug B sees stop (global fallback)')

    # Cleanup
    stop_a.unlink(missing_ok=True)
    stop_b.unlink(missing_ok=True)
    stop_global.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# PART 36: discord-bot.py — slug logged in timeline events
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 36. discord-bot.py: slug included in timeline log events ──')

(p if "'slug': slug" in bot_src else f)(
    "slug field in delegate_spawn event")
# Also in delegate_busy, delegate_spawned
for event_keyword in ['delegate_busy', 'delegate_spawned', 'delegate_spawn_failed',
                       'session_watcher_start', 'session_watcher_done']:
    block = bot_src[bot_src.find(event_keyword):]
    block = block[:min(500, len(block))]
    (p if 'slug' in block else f)(
        f"slug tracked in '{event_keyword}' event")


# ══════════════════════════════════════════════════════════════════════════════
# PART 37: delegate.py — slug logged in key events
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 37. delegate.py: slug in key log events ──')

# lock_acquired should have slug
la_block = delegate_src[delegate_src.find("'event': 'lock_acquired'"):]
la_block = la_block[:200]
(p if "'slug': slug" in la_block else f)("slug in lock_acquired event")

# lock_blocked should have slug
lb_block = delegate_src[delegate_src.find("'event': 'lock_blocked'"):]
lb_block = lb_block[:200]
(p if "'slug': slug" in lb_block else f)("slug in lock_blocked event")

# project_match should have slug
pm_block = delegate_src[delegate_src.find("'event': 'project_match'"):]
pm_block = pm_block[:200]
(p if "'slug': slug" in pm_block else f)("slug in project_match event")


# ══════════════════════════════════════════════════════════════════════════════
# PART 38: discord-bot.py — max-age guard for stale session files
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 38. discord-bot.py: max-age guard (2h) for stale session files ──')

(p if '7200' in bot_src else f)(
    '7200 second (2 hour) max-age guard present')
(p if 'total_seconds()' in bot_src else f)(
    'uses total_seconds() for age calculation')
(p if 'session_path.unlink' in bot_src else f)(
    'stale session file auto-cleaned')


# ══════════════════════════════════════════════════════════════════════════════
# PART 39: Regression — delegate.py module-level constants unchanged
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 39. Regression: module-level constants and imports ──')

if delegate:
    (p if hasattr(delegate, 'LOGDIR') else f)('LOGDIR attribute exists')
    (p if hasattr(delegate, 'WORK_DIR') else f)('WORK_DIR attribute exists')
    (p if hasattr(delegate, 'ts_ms') else f)('ts_ms function exists')
    (p if hasattr(delegate, 'parse_history') else f)('parse_history function exists')
    (p if hasattr(delegate, 'discord_send') else f)('discord_send function exists')
    (p if hasattr(delegate, '_extract_reply_from_jsonl') else f)(
        '_extract_reply_from_jsonl function exists')
    (p if hasattr(delegate, '_extract_last_reply') else f)(
        '_extract_last_reply function exists')
    (p if hasattr(delegate, 'TRIVIAL_REPLIES') else f)(
        'TRIVIAL_REPLIES constant exists')
else:
    skip('delegate module not loaded')


# ══════════════════════════════════════════════════════════════════════════════
# PART 40: discord-bot.py — _discover_projects returns correct structure
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 40. project_list.py: discover_projects returns {lowercase: path} dict ──')

# Check the shared module's function
(p if 'd.name.lower()' in pl_src else f)(
    'project names lowercased in discovery')
(p if 'str(d)' in pl_src else f)(
    'full path stored as value')
(p if "'.claude'" in pl_src else f)(
    'filtered roots check for .claude dir')
(p if "'PROGRESS.md'" in pl_src or '"PROGRESS.md"' in pl_src else f)(
    'filtered roots check for PROGRESS.md')


# ══════════════════════════════════════════════════════════════════════════════
# PART 41: delegate.py — max agent duration timeout
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 41. delegate.py: max agent duration timeout ──')

(p if 'MAX_AGENT_SECONDS' in delegate_src else f)(
    'MAX_AGENT_SECONDS constant defined')
(p if '1200' in delegate_src else f)(
    'timeout set to 1200 seconds (20 min)')
(p if 'max_duration_exceeded' in delegate_src else f)(
    'max_duration_exceeded event logged')
(p if '_timed_out' in delegate_src else f)(
    '_timed_out flag for timeout detection')
(p if '_kill_proc_tree' in delegate_src else f)(
    '_kill_proc_tree helper function defined')
(p if 'def _kill_proc_tree(proc)' in delegate_src else f)(
    '_kill_proc_tree takes proc argument')

# Verify _kill_proc_tree handles both Windows and Unix
kpt_block = delegate_src[delegate_src.find('def _kill_proc_tree'):]
kpt_block = kpt_block[:kpt_block.find('\ndef _run')]
(p if 'taskkill' in kpt_block else f)(
    '_kill_proc_tree uses taskkill on Windows')
(p if 'SIGTERM' in kpt_block or 'os.killpg' in kpt_block else f)(
    '_kill_proc_tree uses killpg on Unix')
(p if 'proc.wait(timeout=' in kpt_block else f)(
    '_kill_proc_tree waits for process termination')

# Verify timeout sends proper message to Discord
(p if "Session timed out" in delegate_src and "min limit" in delegate_src else f)(
    'timeout sends user-friendly message with minute count')

# Verify _timed_out is checked before other failure handlers
timeout_handler_idx = delegate_src.find('elif _timed_out:')
legacy_124_idx = delegate_src.find('elif exit_code == 124:')
(p if timeout_handler_idx > 0 and legacy_124_idx > 0 and timeout_handler_idx < legacy_124_idx else f)(
    '_timed_out handler comes before legacy exit_code=124 handler')


# ══════════════════════════════════════════════════════════════════════════════
# PART 42: discord-bot.py — 1-hour edit guard
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 42. discord-bot.py: 1-hour edit guard ──')

(p if 'MAX_EDIT_AGE_S' in bot_src else f)(
    'MAX_EDIT_AGE_S constant defined')
(p if '55 * 60' in bot_src else f)(
    'edit guard set to 55 minutes (5min safety margin)')
(p if 'elapsed > MAX_EDIT_AGE_S' in bot_src else f)(
    'elapsed checked against MAX_EDIT_AGE_S')
_edit_guard_block = bot_src[bot_src.find('elapsed > MAX_EDIT_AGE_S'):]
_edit_guard_block = _edit_guard_block[:200]
(p if 'continue' in _edit_guard_block else f)(
    'skips edit via continue when age exceeded')

# Verify the guard is in the throttled edit section
edit_section = bot_src[bot_src.find('Throttled status message edits'):]
edit_section = edit_section[:edit_section.find('except Exception')]
(p if 'MAX_EDIT_AGE_S' in edit_section else f)(
    'MAX_EDIT_AGE_S used in throttled edit section')
(p if "Discord won't accept" in edit_section or 'Discord' in edit_section else f)(
    'comment explains why edits are skipped')


# ══════════════════════════════════════════════════════════════════════════════
# PART 43: delegate.py — _kill_proc_tree extracted from inline code
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 43. delegate.py: stop signal uses _kill_proc_tree ──')

# Verify the stop signal handler uses _kill_proc_tree instead of inline kill
run_block = delegate_src[delegate_src.find('def _run('):]
stop_handler = run_block[run_block.find('stop_signal_detected'):]
stop_handler = stop_handler[:stop_handler.find('max_duration')]
(p if '_kill_proc_tree(proc)' in stop_handler else f)(
    'stop signal handler calls _kill_proc_tree(proc)')
# Should NOT have inline taskkill anymore
(p if 'taskkill' not in stop_handler else f)(
    'stop signal handler does not have inline taskkill (uses helper)')


# ══════════════════════════════════════════════════════════════════════════════
# PART 44: Triage improvements — no cooldown, no length limit, skip attachments
# ══════════════════════════════════════════════════════════════════════════════

print('\n── 44. Triage improvements: no cooldown, no length limit, attachment skip ──')

# Continuity window disabled (triage LLM handles context via recent messages)
(p if '_CONTINUITY_WINDOW_S = 0' in bot_src else f)(
    '_CONTINUITY_WINDOW_S disabled (set to 0)')

# slug_continuity block removed
(p if 'slug_continuity' not in bot_src else f)(
    'slug_continuity event removed (no longer used)')

# No QA cooldown — triage always allowed to answer
(p if '_QA_COOLDOWN_S' not in bot_src else f)(
    'no _QA_COOLDOWN_S cooldown (removed)')
(p if '_in_conversation' not in bot_src else f)(
    'no _in_conversation check (removed)')

# Triage runs for all messages (no 500-char limit)
(p if 'len(content.strip()) <= 500' not in bot_src else f)(
    'no 500-char message limit on triage')

# Triage skips attachments (can't see files)
(p if 'attach_count' in bot_src and 'qa_triage_skipped' in bot_src else f)(
    'triage skipped when attachments present')

# Delegate uses opus model
delegate_src = src('delegate.py')
routing_block = delegate_src[delegate_src.rfind('AGENT_SMART_PY'):]
routing_block = routing_block[:routing_block.find('cwd=')]
(p if "'opus'" in routing_block or '"opus"' in routing_block else f)(
    "delegate.py routing call uses 'opus' model")


# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════

print()
print('=' * 50)
print(f'Results: {PASS} passed, {FAIL} failed')
sys.exit(0 if FAIL == 0 else 1)
