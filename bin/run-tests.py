#!/usr/bin/env python3
"""run-tests.py — run all openclaw test suites and report results.

Usage: python run-tests.py [--discord]
  --discord   Send summary to Discord DM after all suites finish.

Exit code: 0 if all suites pass, 1 if any suite fails.
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 stdout on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

REPO_DIR         = Path(__file__).parent.parent
TESTS_DIR        = REPO_DIR / 'tests'
DISCORD_SEND_PY  = Path(__file__).parent / 'discord-send.py'
DISCORD_TARGET   = '1482473282925101217'

SUITES = [
    ('Unit tests',        TESTS_DIR / 'test_delegate.py'),
    ('Integration tests', TESTS_DIR / 'test_integration.py'),
    ('Behavior tests',    TESTS_DIR / 'test_claude_behavior.py'),
]


def run_suite(label, script):
    """Run one test suite, capture output, return (passed, failed, output_lines)."""
    if not script.exists():
        print(f'\n  [SKIP] {label} — {script.name} not found')
        return None, None, [f'SKIP: {script.name} not found']

    print(f'\n{"─"*50}')
    print(f'Running: {label} ({script.name})')
    print('─' * 50)

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(REPO_DIR),
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )

    lines = result.stdout.splitlines()
    for line in lines:
        print(line)
    if result.stderr:
        for line in result.stderr.splitlines():
            print(f'  [stderr] {line}')

    # Parse PASS/FAIL counts from summary line
    passed = failed = 0
    for line in reversed(lines):
        m = re.search(r'(\d+) passed.*?(\d+) failed', line)
        if m:
            passed, failed = int(m.group(1)), int(m.group(2))
            break

    return passed, failed, lines


def send_discord(message):
    """Send summary to Discord via discord-send.py."""
    if not DISCORD_SEND_PY.exists():
        print('[discord] discord-send.py not found — skipping Discord notification')
        return
    try:
        subprocess.run(
            [sys.executable, str(DISCORD_SEND_PY), '--target', DISCORD_TARGET,
             '--message', message],
            timeout=30,
        )
    except Exception as e:
        print(f'[discord] send failed: {e}')


def main():
    parser = argparse.ArgumentParser(description='Run all openclaw test suites')
    parser.add_argument('--discord', action='store_true', help='Send summary to Discord')
    args = parser.parse_args()

    print('╔══════════════════════════════════════════╗')
    print('║   openclaw test runner (Windows)         ║')
    print('╚══════════════════════════════════════════╝')
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    print(f'Started: {ts}')

    total_passed = 0
    total_failed = 0
    suite_results = []

    for label, script in SUITES:
        passed, failed, _ = run_suite(label, script)
        if passed is None:
            suite_results.append((label, 'SKIP', 0, 0))
        else:
            total_passed += passed
            total_failed += failed
            status = 'PASS' if failed == 0 else 'FAIL'
            suite_results.append((label, status, passed, failed))

    print()
    print('SUMMARY')
    print('=' * 50)
    for label, status, passed, failed in suite_results:
        icon = 'PASS' if status == 'PASS' else ('SKIP' if status == 'SKIP' else 'FAIL')
        print(f'  [{icon}] {label}: {passed} passed, {failed} failed')
    print('=' * 50)
    print(f'  Total: {total_passed} passed, {total_failed} failed')

    overall = 'ALL PASS \u2705' if total_failed == 0 else f'{total_failed} FAILED \u274c'
    print(f'\nResult: {overall}')

    if args.discord:
        lines = [f'**openclaw tests — {ts}**']
        for label, status, passed, failed in suite_results:
            icon = '\u2705' if status == 'PASS' else ('\u26a0\ufe0f' if status == 'SKIP' else '\u274c')
            lines.append(f'{icon} {label}: {passed}P {failed}F')
        lines.append(f'\n**Total: {total_passed} passed, {total_failed} failed**')
        lines.append('-# sent by claude')
        send_discord('\n'.join(lines))

    sys.exit(0 if total_failed == 0 else 1)


if __name__ == '__main__':
    main()
