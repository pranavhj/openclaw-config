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


def parse_discord_timeline(events):
    """Parse discord-timeline log for Q&A fast path events, slug routing, and bot restarts."""
    qa_attempts = []  # Each: {ts, content_preview, response_len, elapsed_ms, msg_num}
    slug_routes = []  # Each: {ts, slug, content_preview}
    bot_restarts = 0

    current_qa = None
    for e in events:
        evt = e.get('event', '')

        if evt == 'bot_ready':
            bot_restarts += 1

        elif evt in ('qa_fast_path_attempt', 'qa_triage_attempt'):
            current_qa = {
                'ts': e.get('ts', ''),
                'content_preview': e.get('content_preview', ''),
                'msg_len': e.get('msg_len', 0),
            }

        elif evt in ('qa_fast_path_done', 'qa_triage_done') and current_qa:
            current_qa['response_len'] = e.get('response_len', 0)
            current_qa['elapsed_ms'] = e.get('elapsed_ms', 0)
            current_qa['decision'] = e.get('decision', 'answer')
            qa_attempts.append(current_qa)
            current_qa = None

        elif evt == 'message_received':
            # Track msg_num for follow-up detection
            if current_qa is None:
                pass  # will be picked up by next qa_fast_path_attempt or delegate_spawn

        elif evt == 'delegate_spawn':
            slug_routes.append({
                'ts': e.get('ts', ''),
                'slug': e.get('slug', ''),
                'content_preview': '',  # filled from surrounding message_received
            })

    # Backfill content_preview for slug_routes from message_received events
    msg_events = [e for e in events if e.get('event') == 'message_received']
    for route in slug_routes:
        # Find the closest message_received before this delegate_spawn
        best = None
        for me in msg_events:
            if me.get('ts', '') <= route['ts']:
                best = me
        if best:
            route['content_preview'] = best.get('content_preview', '')
            route['msg_num'] = best.get('num', 1)

    # Backfill msg_num for qa_attempts from message_received events
    for qa in qa_attempts:
        best = None
        for me in msg_events:
            if me.get('ts', '') <= qa['ts']:
                best = me
        if best:
            qa['msg_num'] = best.get('num', 1)

    return {
        'qa_attempts': qa_attempts,
        'slug_routes': slug_routes,
        'bot_restarts': bot_restarts,
    }


def check_qa_misfires(discord_data, known_project_names=None):
    """Detect Q&A fast path misfires: follow-ups intercepted, project-related questions answered by Q&A."""
    issues = []

    for qa in discord_data['qa_attempts']:
        preview = qa.get('content_preview', '').lower()
        msg_num = qa.get('msg_num', 1)

        # Follow-up detection: msg_num > 1 means it's not the first message in a session
        followup_words = {'above', 'again', 'retry', 'previous', 'before', 'earlier', 'last',
                          'same', 'that', 'those', 'redo', 'repeat'}
        words = set(re.findall(r'\b\w+\b', preview))
        has_followup = bool(words & followup_words)

        if msg_num > 1 or has_followup:
            issues.append({
                'type': 'qa_followup_intercepted',
                'severity': 'high',
                'ts': qa.get('ts', ''),
                'detail': f'Q&A intercepted follow-up (msg #{msg_num}): "{qa.get("content_preview", "")[:60]}"',
            })

        # Project name in Q&A question
        if known_project_names:
            for name in known_project_names:
                if name in preview or (len(name) >= 4 and any(
                    w.startswith(name[:4]) for w in words
                )):
                    issues.append({
                        'type': 'qa_project_intercepted',
                        'severity': 'medium',
                        'ts': qa.get('ts', ''),
                        'detail': f'Q&A answered project-related question ({name}): "{qa.get("content_preview", "")[:60]}"',
                    })
                    break

    return issues


def check_slug_misroutes(discord_data, known_project_names=None):
    """Detect messages that went to router but mention a specific project."""
    issues = []
    if not known_project_names:
        return issues

    for route in discord_data['slug_routes']:
        if route['slug'] == 'router':
            preview = route.get('content_preview', '').lower()
            words = set(re.findall(r'\b\w+\b', preview))
            for name in known_project_names:
                # Check exact match or close spelling
                if name in words:
                    issues.append({
                        'type': 'slug_misroute',
                        'severity': 'medium',
                        'ts': route.get('ts', ''),
                        'detail': f'Message mentions "{name}" but routed to router: "{route.get("content_preview", "")[:60]}"',
                    })
                    break
                # Check prefix match (min 4 chars) — same logic as bot
                for w in words:
                    if len(w) >= 4 and name.startswith(w) and name != w:
                        issues.append({
                            'type': 'slug_misroute',
                            'severity': 'low',
                            'ts': route.get('ts', ''),
                            'detail': f'Message has prefix "{w}" for project "{name}" but routed to router: "{route.get("content_preview", "")[:60]}"',
                        })
                        break

    return issues


def parse_all_slug_timelines(date_str):
    """Read all timeline-{slug}-{date}.log files. Returns per-slug stats and cross-slug issues."""
    import glob as _glob
    pattern = str(LOG_DIR / f'timeline-*-{date_str}.log')
    files = _glob.glob(pattern)

    slug_stats = {}  # slug → {interactions, timeouts, slow_warnings, max_duration_ms, failures}
    timeout_issues = []

    for fpath in files:
        fname = Path(fpath).name
        # Extract slug from timeline-{slug}-{date}.log
        prefix = 'timeline-'
        suffix = f'-{date_str}.log'
        if not fname.startswith(prefix) or not fname.endswith(suffix):
            continue
        slug = fname[len(prefix):-len(suffix)]

        events = load_jsonl(Path(fpath))
        stats = {
            'interactions': 0,
            'timeouts': 0,
            'slow_warnings': 0,
            'failures': 0,
            'max_duration_ms': 0,
        }

        for e in events:
            evt = e.get('event', '')
            if evt == 'delegate_recv':
                stats['interactions'] += 1
            elif evt == 'max_duration_exceeded':
                stats['timeouts'] += 1
                elapsed = e.get('elapsed_s', 0)
                timeout_issues.append({
                    'type': 'timeout_killed',
                    'severity': 'high',
                    'slug': slug,
                    'ts': e.get('ts', ''),
                    'detail': f'{slug} killed after {elapsed}s (limit {e.get("limit_s", "?")}s)',
                })
            elif evt == 'slow_warning':
                stats['slow_warnings'] += 1
            elif evt == 'failure_detected':
                stats['failures'] += 1
            elif evt == 'delegate_exit':
                ms = e.get('total_ms', 0)
                if ms > stats['max_duration_ms']:
                    stats['max_duration_ms'] = ms

        slug_stats[slug] = stats

    return slug_stats, timeout_issues


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
                current['issues'].append(('stdout_forward', 'low', 'Claude printed to stdout — forwarded by delegate'))

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
        # MAX_AGENT_SECONDS is 1200 (20min); near_timeout = 90% of that
        if total_ms >= 1080000:
            interaction['issues'].append(('near_timeout', 'high', f'{total_ms // 1000}s (≥18min)'))
        elif total_ms >= 300000:
            interaction['issues'].append(('slow', 'medium', f'{total_ms // 1000}s (≥5min)'))

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


def format_report(date_str, interactions, gateway_stats,
                   discord_data=None, slug_stats=None, extra_issues=None):
    total = len(interactions)
    all_issues = [issue for i in interactions for issue in i['issues']]
    high = [x for x in all_issues if x[1] == 'high']
    medium = [x for x in all_issues if x[1] == 'medium']
    low = [x for x in all_issues if x[1] == 'low']

    # Count extra issues from discord/slug analysis
    extra_issues = extra_issues or []
    extra_high = [x for x in extra_issues if x['severity'] == 'high']
    extra_medium = [x for x in extra_issues if x['severity'] == 'medium']
    extra_low = [x for x in extra_issues if x['severity'] == 'low']

    total_high = len(high) + len(extra_high)
    total_medium = len(medium) + len(extra_medium)
    total_low = len(low) + len(extra_low)

    failed = sum(1 for i in interactions
                 if any(x[0] in ('exit_nonzero', 'no_reply', 'failure_detected') for x in i['issues']))
    slow = sum(1 for i in interactions if i['total_ms'] and i['total_ms'] >= 300000)

    status = '✅' if not total_high else ('⚠️' if total_high <= 2 else '🔴')

    lines = [f"**Nightly Audit — {date_str}** {status}"]
    lines.append("")

    # Per-slug breakdown (from all timeline files)
    if slug_stats:
        slug_parts = []
        for slug, stats in sorted(slug_stats.items()):
            parts = [f"{stats['interactions']}"]
            if stats['timeouts']:
                parts.append(f"{stats['timeouts']} timed out")
            if stats['failures']:
                parts.append(f"{stats['failures']} failed")
            slug_parts.append(f"{slug}: {', '.join(parts)}")
        lines.append(f"Delegates: {', '.join(slug_parts)}")
    elif total > 0:
        parts = [f"{total} total"]
        if failed:
            parts.append(f"{failed} failed")
        if slow:
            parts.append(f"{slow} slow")
        lines.append(f"Discord: {', '.join(parts)}")
    else:
        lines.append("Discord: no interactions")

    # Q&A fast path stats
    if discord_data and discord_data['qa_attempts']:
        qa = discord_data['qa_attempts']
        avg_ms = sum(q.get('elapsed_ms', 0) for q in qa) // len(qa) if qa else 0
        lines.append(f"Q&A fast path: {len(qa)} handled, avg {avg_ms}ms")

    # Bot restarts
    if discord_data and discord_data.get('bot_restarts', 0) > 1:
        lines.append(f"Bot restarts: {discord_data['bot_restarts']}")

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
    all_issue_count = total_high + total_medium + total_low
    if all_issue_count:
        lines.append("")
        lines.append(f"Issues: {total_high} high / {total_medium} medium / {total_low} low")
        for i in interactions:
            if not i['issues']:
                continue
            project = i.get('project') or 'unknown'
            preview = (i['msg_preview'] or '')[:50]
            tags = ', '.join(f"{x[0]}" for x in i['issues'])
            lines.append(f"- [{project}] \"{preview}\" → {tags}")
        for ei in extra_issues:
            lines.append(f"- [{ei.get('type', '?')}] {ei.get('detail', '')[:80]}")
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


def phase2_quality_score(token, interactions, date_str, extra_issues=None):
    """Call gateway to quality-score flagged high-severity interactions + extra issues."""
    flagged = [
        i for i in interactions
        if any(x[1] == 'high' for x in i['issues'])
        and not any(x[0] == 'user_stopped' for x in i['issues'])
    ]
    extra_high = [x for x in (extra_issues or []) if x['severity'] == 'high']

    if not flagged and not extra_high:
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

    if extra_high:
        lines.append("")
        lines.append("Additional issues from discord-timeline analysis:")
        for ei in extra_high:
            lines.append(f'- [{ei["type"]}] {ei["detail"][:100]}')

    lines.append("\nKeep your response under 5 bullet points. Be concrete.")
    return call_gateway(token, '\n'.join(lines))


def phase3_optimization(token, interactions, gateway_stats, date_str,
                         discord_data=None, slug_stats=None, extra_issues=None):
    """Call gateway for optimization suggestions based on observed patterns."""
    total = len(interactions)
    extra_issues = extra_issues or []

    high_count = (
        sum(1 for i in interactions for x in i['issues'] if x[1] == 'high')
        + sum(1 for x in extra_issues if x['severity'] == 'high')
    )
    slow_count = sum(1 for i in interactions if i['total_ms'] and i['total_ms'] >= 300000)
    failed_count = sum(
        1 for i in interactions
        if any(x[0] in ('exit_nonzero', 'no_reply', 'failure_detected') for x in i['issues'])
    )
    timeout_count = sum(1 for x in extra_issues if x['type'] == 'timeout_killed')
    qa_misfire_count = sum(1 for x in extra_issues if x['type'] in ('qa_followup_intercepted', 'qa_project_intercepted'))
    misroute_count = sum(1 for x in extra_issues if x['type'] == 'slug_misroute')

    if high_count == 0 and slow_count == 0 and not extra_issues:
        return None

    issue_types = set(
        x[0] for i in interactions for x in i['issues']
    ) | set(x['type'] for x in extra_issues)

    prompt = (
        f"Openclaw system audit — {date_str}\n"
        f"System: Discord → discord-bot.py (slug matching + Q&A fast path) → delegate.py → Claude agent\n\n"
        f"Stats:\n"
        f"- Router interactions: {total}\n"
        f"- High-severity issues: {high_count}\n"
        f"- Failed (no reply / nonzero exit): {failed_count}\n"
        f"- Slow (>5min): {slow_count}\n"
        f"- Timed out (killed by MAX_AGENT_SECONDS): {timeout_count}\n"
        f"- Q&A fast path misfires: {qa_misfire_count}\n"
        f"- Slug misroutes (wrong project): {misroute_count}\n"
    )

    if slug_stats:
        prompt += f"- Per-slug breakdown: {json.dumps(slug_stats)}\n"

    if discord_data:
        qa = discord_data.get('qa_attempts', [])
        prompt += f"- Q&A fast path: {len(qa)} handled"
        if discord_data.get('bot_restarts', 0) > 1:
            prompt += f", bot restarted {discord_data['bot_restarts']} times"
        prompt += "\n"

    prompt += (
        f"- Gateway /ask: {gateway_stats['ask_requests']} requests, "
        f"{gateway_stats['ask_errors']} errors\n"
        f"- Issue types seen: {', '.join(sorted(issue_types)) or 'none'}\n\n"
    )

    if extra_issues:
        prompt += "Specific issues found:\n"
        for ei in extra_issues[:10]:  # Cap at 10 to avoid prompt bloat
            prompt += f"- [{ei['type']}] {ei['detail'][:120]}\n"
        prompt += "\n"

    prompt += (
        f"Suggest 2-3 concrete, actionable improvements to reduce failures, misfires, or misroutes. "
        f"Focus on: slug matching aliases, Q&A fast path guards, timeout tuning. "
        f"Be specific. Under 5 bullet points."
    )
    return call_gateway(token, prompt)


def _discover_project_names():
    """Discover known project names using shared project_list module."""
    from project_list import discover_projects
    return set(discover_projects().keys())


def main():
    if len(sys.argv) > 1:
        target_date = datetime.strptime(sys.argv[1], '%Y-%m-%d').date()
    else:
        target_date = date.today() - timedelta(days=1)

    date_str = target_date.strftime('%Y-%m-%d')

    # ── Load all log sources ──
    router_log = LOG_DIR / f'timeline-router-{date_str}.log'
    router_events = load_jsonl(router_log)

    interactions = parse_router_interactions(router_events)
    for i in interactions:
        check_interaction(i)

    gateway_log = LOG_DIR / f'gateway-timeline-{date_str}.log'
    gateway_events = load_jsonl(gateway_log)
    gateway_stats = parse_gateway_stats(gateway_events)

    # NEW: Discord timeline (Q&A fast path, slug routing, bot restarts)
    discord_log = LOG_DIR / f'discord-timeline-{date_str}.log'
    discord_events = load_jsonl(discord_log)
    discord_data = parse_discord_timeline(discord_events)

    # NEW: All per-slug timelines (timeouts, per-project stats)
    slug_stats, timeout_issues = parse_all_slug_timelines(date_str)

    # NEW: Detect Q&A misfires and slug misroutes
    known_projects = _discover_project_names()
    qa_issues = check_qa_misfires(discord_data, known_projects)
    misroute_issues = check_slug_misroutes(discord_data, known_projects)
    extra_issues = qa_issues + misroute_issues + timeout_issues

    has_any_data = router_events or gateway_events or discord_events or slug_stats
    if not has_any_data:
        send_discord(
            f"**Nightly Audit — {date_str}** ℹ️\n"
            f"No log files found for this date.\n\n-# sent by claude"
        )
        return

    report = format_report(date_str, interactions, gateway_stats,
                           discord_data=discord_data, slug_stats=slug_stats,
                           extra_issues=extra_issues)
    send_discord(report)

    # Phase 2 + 3: AI-assisted analysis via LLM gateway (best-effort)
    token = load_gateway_token()
    if token:
        quality = phase2_quality_score(token, interactions, date_str, extra_issues=extra_issues)
        if quality:
            send_discord(f"**Quality Assessment**\n{quality}\n\n-# sent by claude")

        suggestions = phase3_optimization(
            token, interactions, gateway_stats, date_str,
            discord_data=discord_data, slug_stats=slug_stats, extra_issues=extra_issues,
        )
        if suggestions:
            send_discord(f"**Optimization Suggestions**\n{suggestions}\n\n-# sent by claude")

        autofix = phase4_autofix(token, suggestions, date_str)
        if autofix:
            send_discord(f"**Auto-fix Results**\n{autofix}\n\n-# sent by claude")


if __name__ == '__main__':
    main()
