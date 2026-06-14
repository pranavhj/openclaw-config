#!/usr/bin/env python3
"""
nightly-audit.py — openclaw log health checker

Runs daily at 03:30 via Windows Task Scheduler.
Audits yesterday's interaction logs and sends a health report to Discord DM.

Phase 1: Rule-based checks (no tokens)
Phase 2: LLM Gateway quality scoring for flagged sessions
Phase 3: LLM Gateway optimization suggestions based on patterns

Usage:
    python nightly-audit.py               # audit yesterday
    python nightly-audit.py 2026-06-13   # audit specific date
"""

import json
import os
import re
import sys
import subprocess
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

LOG_DIR = Path(os.environ.get('LOCALAPPDATA', r'C:\Users\prana\AppData\Local')) / 'openclaw'
DISCORD_SEND = str(Path(__file__).parent / 'discord-send.py')
DISCORD_TARGET = '1482473282925101217'
GATEWAY_URL = 'http://127.0.0.1:18789'
GATEWAY_PROJECT = 'nightly_audit'
REPO_DIR = Path(__file__).parent.parent

# Files that need architecture caution: re-read + trace deps before touching
PROTECTED_FILES = {
    'bin/llm-gateway.py',
    'bin/gateway-delegate.py',
    'bin/project_store.py',
    'bin/discord-bot.py',
    'bin/discord-send.py',
}


def send_discord(msg):
    subprocess.run([sys.executable, DISCORD_SEND, '--target', DISCORD_TARGET, '--message', msg])


# ── Safe-change scaffolding ──────────────────────────────────────────────────

def run_tests():
    """Run the openclaw test suite. Returns (passed, failed), or (-1, -1) on error."""
    try:
        result = subprocess.run(
            [sys.executable, str(REPO_DIR / 'bin' / 'run-tests.py')],
            cwd=str(REPO_DIR),
            capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=300,
        )
        for line in reversed(result.stdout.splitlines()):
            m = re.search(r'(\d+) passed.*?(\d+) failed', line)
            if m:
                return int(m.group(1)), int(m.group(2))
        return 0, 0
    except Exception:
        return -1, -1


def check_file_safety(file_path):
    """Check if a file needs architecture caution before editing.
    Returns (is_protected: bool, info: str|None).
    """
    try:
        rel = str(Path(file_path).relative_to(REPO_DIR)).replace('\\', '/')
    except ValueError:
        rel = str(file_path).replace('\\', '/')
    if rel in PROTECTED_FILES:
        try:
            lines = len(Path(file_path).read_text(encoding='utf-8').splitlines())
            return True, f'{rel} ({lines} lines) — re-read before any change'
        except Exception:
            return True, f'{rel} — could not read'
    return False, None


def safe_change_cycle(desc, file_path, old_snippet, new_snippet, new_test_code=None):
    """Apply a code change with the full safe cycle:
      1. Run baseline tests
      2. Apply change
      3. Run tests again
      4. Write new tests (if provided)
      5. Run tests one more time
      6. Commit and push

    Returns (success: bool, message: str).
    If any step fails, reverts and returns (False, reason).
    """
    file_path = Path(file_path)

    # Architecture caution: protected files need extra verification
    is_protected, _ = check_file_safety(file_path)
    if is_protected:
        try:
            current = file_path.read_text(encoding='utf-8')
        except Exception as e:
            return False, f'Cannot read protected file {file_path.name}: {e}'
        if old_snippet not in current:
            return False, f'Protected {file_path.name}: old_snippet not found — skipping'
        if len(new_snippet) - len(old_snippet) > 200:
            return False, f'Protected {file_path.name}: change delta >200 chars — too large, skipping'

    # Step 1: Baseline tests
    passed0, failed0 = run_tests()
    if passed0 == -1:
        return False, 'Test runner error — aborting'
    if failed0 > 0:
        return False, f'Baseline tests failing ({failed0} failed) — aborting change'

    # Step 2: Apply change
    try:
        original = file_path.read_text(encoding='utf-8')
    except Exception as e:
        return False, f'Cannot read {file_path.name}: {e}'
    if old_snippet not in original:
        return False, f'{file_path.name}: old_snippet not found'
    modified = original.replace(old_snippet, new_snippet, 1)
    try:
        file_path.write_text(modified, encoding='utf-8')
    except Exception as e:
        return False, f'Cannot write {file_path.name}: {e}'

    # Step 3: Tests after change
    passed1, failed1 = run_tests()
    if failed1 > 0 or passed1 < passed0:
        try:
            file_path.write_text(original, encoding='utf-8')
        except Exception:
            pass
        return False, f'Tests broke after change ({failed1} failed) — reverted'

    # Step 4: Write new tests (append before Summary marker)
    original_tests = None
    test_file = REPO_DIR / 'tests' / 'test_nightly_audit.py'
    if new_test_code:
        try:
            original_tests = test_file.read_text(encoding='utf-8')
            marker = '# ── Summary'
            if marker in original_tests:
                new_tests_text = original_tests.replace(
                    marker, new_test_code + '\n\n' + marker, 1
                )
            else:
                new_tests_text = original_tests + '\n\n' + new_test_code
            test_file.write_text(new_tests_text, encoding='utf-8')
        except Exception:
            new_test_code = None  # Non-fatal: skip new-test step

    # Step 5: Tests with new tests included
    if new_test_code:
        passed2, failed2 = run_tests()
        if failed2 > 0:
            try:
                file_path.write_text(original, encoding='utf-8')
                if original_tests:
                    test_file.write_text(original_tests, encoding='utf-8')
            except Exception:
                pass
            return False, f'New tests failed ({failed2} failed) — reverted change and tests'

    # Step 6: Commit and push
    try:
        subprocess.run(['git', 'add', '-A'], cwd=str(REPO_DIR), check=True, capture_output=True)
        subprocess.run(
            ['git', 'commit', '-m', f'fix(audit): {desc}'],
            cwd=str(REPO_DIR), check=True, capture_output=True,
        )
        subprocess.run(['git', 'push'], cwd=str(REPO_DIR), check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        return False, f'Git failed: {e}'

    return True, f'Applied and pushed: {desc}'


def phase4_autofix(token, phase3_suggestions, date_str):
    """Ask gateway for concrete patches based on Phase 3 suggestions, then apply each
    one using safe_change_cycle. Returns a summary string or None.
    """
    if not phase3_suggestions:
        return None

    prompt = (
        f'Openclaw nightly audit — {date_str}\n'
        f'Phase 3 optimization suggestions:\n{phase3_suggestions}\n\n'
        f'Generate up to 2 conservative, targeted code patches to implement '
        f'the most impactful suggestion.\n'
        f'Respond with one JSON object per line (no other text):\n'
        f'{{"file": "bin/relative.py", "desc": "short description", '
        f'"old": "exact text to replace", "new": "replacement text", '
        f'"test": "# new test code to add or null"}}\n\n'
        f'Rules:\n'
        f'- Only patch files in bin/ (delegate.py, agent-smart.py, route-audit.py, etc.)\n'
        f'- Do NOT patch: discord-bot.py, discord-send.py, llm-gateway.py, '
        f'gateway-delegate.py, project_store.py\n'
        f'- Make minimal changes — prefer threshold/constant tweaks over logic rewrites\n'
        f'- If no safe patch is possible, respond with an empty line'
    )
    response = call_gateway(token, prompt)
    if not response:
        return None

    results = []
    for line in response.splitlines():
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            patch = json.loads(line)
        except json.JSONDecodeError:
            continue

        file_rel = patch.get('file', '')
        desc = patch.get('desc', '')
        old_snip = patch.get('old', '')
        new_snip = patch.get('new', '')
        test_code = patch.get('test') or None

        if not (file_rel and desc and old_snip and new_snip):
            results.append(f'SKIP: incomplete patch for {file_rel or "unknown"}')
            continue

        file_path = REPO_DIR / file_rel.lstrip('/')
        if not file_path.exists():
            results.append(f'SKIP: {file_rel} not found')
            continue

        success, msg = safe_change_cycle(desc, file_path, old_snip, new_snip, test_code)
        results.append(f'{"OK" if success else "FAIL"}: {msg}')

    return '\n'.join(results) if results else None


def load_jsonl(path):
    events = []
    if not path.exists():
        return events
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events


def parse_router_interactions(events):
    """Group router timeline events into one record per delegate_recv→delegate_exit pair."""
    interactions = []
    current = None

    for e in events:
        evt = e.get('event', '')

        if evt == 'delegate_recv':
            if current:
                # Previous interaction never closed
                current['issues'].append(('no_exit', 'high', 'no delegate_exit seen'))
                interactions.append(current)
            current = {
                'ts': e.get('ts', ''),
                'msg_preview': e.get('msg_preview', ''),
                'msg_len': e.get('msg_len', 0),
                'project': None,
                'prompt_bytes': 0,
                'exit_code': None,
                'total_ms': None,
                'has_reply': False,
                'has_failure_event': False,
                'has_stop_signal': False,
                'issues': [],
            }

        elif current is not None:
            if evt == 'project_match':
                current['project'] = e.get('project', '')
            elif evt == 'prompt_ready':
                current['prompt_bytes'] = e.get('bytes', 0)
            elif evt == 'agent_done':
                current['exit_code'] = e.get('exit_code')
            elif evt == 'delegate_reply':
                reply = e.get('reply_preview', '')
                # Only count as replied if output actually contains SENT
                current['has_reply'] = True
            elif evt == 'delegate_exit':
                current['total_ms'] = e.get('total_ms')
                final = str(e.get('final_output', ''))
                if 'SENT' not in final:
                    current['has_reply'] = False
                interactions.append(current)
                current = None
            elif evt == 'failure_detected':
                current['has_failure_event'] = True
            elif evt == 'stop_signal_detected':
                current['has_stop_signal'] = True
            elif evt == 'lock_blocked':
                current['issues'].append(('lock_blocked', 'high', 'concurrent request dropped'))
            elif evt == 'stale_lock_broken':
                current['issues'].append(('stale_lock', 'medium', 'previous run crashed without cleanup'))
            elif evt == 'stdout_forward':
                current['issues'].append(('stdout_forward', 'medium', 'Claude printed to stdout instead of discord-send'))

    if current:
        current['issues'].append(('no_exit', 'high', 'no delegate_exit seen'))
        interactions.append(current)

    return interactions


def check_interaction(interaction):
    """Apply rule-based checks and append issues to the interaction."""
    if interaction['has_stop_signal']:
        # User manually stopped — tag it but not as an error
        interaction['issues'].append(('user_stopped', 'low', 'stopped by user'))
        return

    exit_code = interaction['exit_code']
    total_ms = interaction['total_ms']

    if exit_code is not None and exit_code != 0:
        interaction['issues'].append(('exit_nonzero', 'high', f'exit_code={exit_code}'))

    if interaction['has_failure_event']:
        interaction['issues'].append(('failure_detected', 'high', 'explicit failure_detected event'))
    elif not interaction['has_reply']:
        interaction['issues'].append(('no_reply', 'high', 'no SENT in final output'))

    if total_ms is not None:
        if total_ms >= 110000:
            interaction['issues'].append(('near_timeout', 'high', f'{total_ms // 1000}s (≥110s)'))
        elif total_ms >= 60000:
            interaction['issues'].append(('slow', 'medium', f'{total_ms // 1000}s (≥60s)'))

    if 0 < interaction['prompt_bytes'] < 800:
        interaction['issues'].append(('tiny_prompt', 'low', f'{interaction["prompt_bytes"]}B prompt'))


def parse_gateway_stats(events):
    """Summarize LLM gateway /ask and /data activity."""
    ask_sessions = {}
    data_posts = 0
    ask_errors = 0
    ask_durations = []

    for e in events:
        sid = e.get('sid', '')
        evt = e.get('event', '')

        if evt == 'ask_received':
            ask_sessions[sid] = {'done': False, 'status': None, 'duration_ms': None}
        elif evt == 'data_post_received':
            data_posts += 1
        elif evt == 'request_done' and sid in ask_sessions:
            s = ask_sessions[sid]
            s['done'] = True
            s['status'] = e.get('status')
            s['duration_ms'] = e.get('duration_ms')
            if (e.get('status') or 200) >= 400:
                ask_errors += 1
            if e.get('duration_ms') is not None:
                ask_durations.append(e['duration_ms'])

    avg_ms = int(sum(ask_durations) / len(ask_durations)) if ask_durations else None
    return {
        'ask_requests': len(ask_sessions),
        'ask_errors': ask_errors,
        'data_posts': data_posts,
        'avg_duration_ms': avg_ms,
    }


def format_report(date_str, interactions, gateway_stats):
    total = len(interactions)
    all_issues = [issue for i in interactions for issue in i['issues']]
    high = [x for x in all_issues if x[1] == 'high']
    medium = [x for x in all_issues if x[1] == 'medium']
    low = [x for x in all_issues if x[1] == 'low']

    failed = sum(1 for i in interactions
                 if any(x[0] in ('exit_nonzero', 'no_reply', 'failure_detected') for x in i['issues']))
    slow = sum(1 for i in interactions if i['total_ms'] and i['total_ms'] >= 60000)

    status = '✅' if not high else ('⚠️' if len(high) <= 2 else '🔴')

    lines = [f"**Nightly Audit — {date_str}** {status}"]
    lines.append("")

    # Discord interactions summary
    if total > 0:
        parts = [f"{total} total"]
        if failed:
            parts.append(f"{failed} failed")
        if slow:
            parts.append(f"{slow} slow")
        lines.append(f"Discord: {', '.join(parts)}")
    else:
        lines.append("Discord: no interactions")

    # Gateway summary
    if gateway_stats['ask_requests'] > 0:
        gw = f"Gateway /ask: {gateway_stats['ask_requests']} requests"
        if gateway_stats['ask_errors']:
            gw += f", {gateway_stats['ask_errors']} errors"
        if gateway_stats['avg_duration_ms']:
            gw += f", avg {gateway_stats['avg_duration_ms']}ms"
        lines.append(gw)
    if gateway_stats['data_posts'] > 0:
        lines.append(f"Gateway /data: {gateway_stats['data_posts']} posts")

    # Issues
    if all_issues:
        lines.append("")
        lines.append(f"Issues: {len(high)} high / {len(medium)} medium / {len(low)} low")
        for i in interactions:
            if not i['issues']:
                continue
            project = i.get('project') or 'unknown'
            preview = (i['msg_preview'] or '')[:50]
            tags = ', '.join(f"{x[0]}" for x in i['issues'])
            lines.append(f"- [{project}] \"{preview}\" → {tags}")
    else:
        lines.append("")
        lines.append("No issues found.")

    lines.append("")
    lines.append("-# sent by claude")
    return '\n'.join(lines)


def load_gateway_token():
    config_path = Path.home() / '.openclaw' / 'openclaw.json'
    try:
        with open(config_path, encoding='utf-8') as f:
            return json.load(f)['gateway']['auth']['token']
    except Exception:
        return None


def call_gateway(token, message):
    payload = json.dumps({'project': GATEWAY_PROJECT, 'message': message, 'context': 'none'}).encode()
    req = urllib.request.Request(
        f'{GATEWAY_URL}/ask',
        data=payload,
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read()).get('response', '')
    except Exception:
        return None


def phase2_quality_score(token, interactions, date_str):
    """Call gateway to quality-score flagged high-severity interactions."""
    flagged = [
        i for i in interactions
        if any(x[1] == 'high' for x in i['issues'])
        and not any(x[0] == 'user_stopped' for x in i['issues'])
    ]
    if not flagged:
        return None

    lines = [
        f"Openclaw router audit — {date_str}",
        "These Discord interactions were flagged with high-severity issues.",
        "For each, briefly assess: was the project routing plausible? Any obvious pattern?",
        "",
    ]
    for i in flagged:
        msg = (i.get('msg_preview') or '')[:80]
        project = i.get('project') or 'unknown'
        issues = ', '.join(x[0] for x in i['issues'])
        lines.append(f'- User: "{msg}" → [{project}], issues: {issues}')

    lines.append("\nKeep your response under 5 bullet points. Be concrete.")
    return call_gateway(token, '\n'.join(lines))


def phase3_optimization(token, interactions, gateway_stats, date_str):
    """Call gateway for optimization suggestions based on observed patterns."""
    total = len(interactions)
    if total == 0:
        return None

    high_count = sum(1 for i in interactions for x in i['issues'] if x[1] == 'high')
    slow_count = sum(1 for i in interactions if i['total_ms'] and i['total_ms'] >= 60000)
    failed_count = sum(
        1 for i in interactions
        if any(x[0] in ('exit_nonzero', 'no_reply', 'failure_detected') for x in i['issues'])
    )

    if high_count == 0 and slow_count == 0:
        return None

    issue_types = ', '.join(
        x[0] for i in interactions for x in i['issues']
    ) or 'none'

    prompt = (
        f"Openclaw router system audit — {date_str}\n"
        f"System: Discord → delegate.py → Claude router → project sub-sessions\n\n"
        f"Stats:\n"
        f"- Total interactions: {total}\n"
        f"- High-severity issues: {high_count}\n"
        f"- Failed (no reply / nonzero exit): {failed_count}\n"
        f"- Slow (>60s): {slow_count}\n"
        f"- Gateway /ask: {gateway_stats['ask_requests']} requests, "
        f"{gateway_stats['ask_errors']} errors\n"
        f"- Issue types seen: {issue_types}\n\n"
        f"Suggest 2-3 concrete, actionable improvements to reduce failures or slow responses. "
        f"Be specific. Under 5 bullet points."
    )
    return call_gateway(token, prompt)


def main():
    if len(sys.argv) > 1:
        target_date = datetime.strptime(sys.argv[1], '%Y-%m-%d').date()
    else:
        target_date = date.today() - timedelta(days=1)

    date_str = target_date.strftime('%Y-%m-%d')

    router_log = LOG_DIR / f'timeline-router-{date_str}.log'
    router_events = load_jsonl(router_log)

    interactions = parse_router_interactions(router_events)
    for i in interactions:
        check_interaction(i)

    gateway_log = LOG_DIR / f'gateway-timeline-{date_str}.log'
    gateway_events = load_jsonl(gateway_log)
    gateway_stats = parse_gateway_stats(gateway_events)

    if not router_events and not gateway_events:
        send_discord(
            f"**Nightly Audit — {date_str}** ℹ️\n"
            f"No log files found for this date.\n\n-# sent by claude"
        )
        return

    report = format_report(date_str, interactions, gateway_stats)
    send_discord(report)

    # Phase 2 + 3: AI-assisted analysis via LLM gateway (best-effort)
    token = load_gateway_token()
    if token:
        quality = phase2_quality_score(token, interactions, date_str)
        if quality:
            send_discord(f"**Quality Assessment**\n{quality}\n\n-# sent by claude")

        suggestions = phase3_optimization(token, interactions, gateway_stats, date_str)
        if suggestions:
            send_discord(f"**Optimization Suggestions**\n{suggestions}\n\n-# sent by claude")

        autofix = phase4_autofix(token, suggestions, date_str)
        if autofix:
            send_discord(f"**Auto-fix Results**\n{autofix}\n\n-# sent by claude")


if __name__ == '__main__':
    main()
