#!/usr/bin/env python3
"""
Unit tests for nightly-audit.py — Phase 1, 2, 3.

Tests:
  - parse_router_interactions: grouping, unclosed, lock events
  - check_interaction: all rule-based checks (exit_nonzero, no_reply, near_timeout, slow, tiny_prompt, user_stopped)
  - parse_gateway_stats: ask/data/error/duration tracking
  - format_report: status icon, sections, watermark
  - load_gateway_token: reads config correctly, handles missing
  - phase2_quality_score: skips when no flagged, skips user_stopped only
  - phase3_optimization: skips when no high/slow
  - load_jsonl: valid lines, empty lines, malformed JSON
  - script structure: required functions, constants, watermark
"""
import importlib.util
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
BIN_DIR = REPO_DIR / 'bin'
NIGHTLY_AUDIT_PY = BIN_DIR / 'nightly-audit.py'

sys.path.insert(0, str(BIN_DIR))


def p(msg):
    global PASS; PASS += 1
    print(f'  PASS: {msg}')


def f(msg):
    global FAIL; FAIL += 1
    print(f'  FAIL: {msg}')


def skip(msg):
    print(f'  SKIP: {msg}')


def load_nightly_audit():
    """Import nightly_audit module without executing main()."""
    spec = importlib.util.spec_from_file_location('nightly_audit', NIGHTLY_AUDIT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


src = NIGHTLY_AUDIT_PY.read_text(encoding='utf-8')

# ── 1. Script presence ──────────────────────────────────────────────────────
print('\n1. Script presence')
(p if NIGHTLY_AUDIT_PY.exists() else f)('nightly-audit.py exists')

# ── 2. Module imports ───────────────────────────────────────────────────────
print('\n2. Module imports')
try:
    na = load_nightly_audit()
    p('nightly-audit.py imports cleanly')
except Exception as e:
    f(f'nightly-audit.py import failed: {e}')
    na = None

# ── 3. load_jsonl ───────────────────────────────────────────────────────────
print('\n3. load_jsonl')
if na:
    with tempfile.NamedTemporaryFile('w', suffix='.log', delete=False, encoding='utf-8') as tf:
        tf.write('{"event": "delegate_recv", "ts": "2026-06-13T00:00:00Z"}\n')
        tf.write('\n')
        tf.write('not-json-at-all\n')
        tf.write('{"event": "delegate_exit", "total_ms": 5000}\n')
        tf_path = Path(tf.name)

    events = na.load_jsonl(tf_path)
    (p if len(events) == 2 else f)(f'load_jsonl: 2 valid events (got {len(events)})')
    (p if events[0].get('event') == 'delegate_recv' else f)('load_jsonl: first event correct')
    (p if events[1].get('event') == 'delegate_exit' else f)('load_jsonl: second event correct')

    # Non-existent file returns empty list
    events_empty = na.load_jsonl(Path('/nonexistent/file.log'))
    (p if events_empty == [] else f)('load_jsonl: non-existent file returns []')
    tf_path.unlink(missing_ok=True)

# ── 4. parse_router_interactions ────────────────────────────────────────────
print('\n4. parse_router_interactions')
if na:
    # Basic pair
    events = [
        {'event': 'delegate_recv', 'ts': 'T1', 'msg_preview': 'hello', 'msg_len': 5},
        {'event': 'project_match', 'project': 'shaadibot'},
        {'event': 'prompt_ready', 'bytes': 1200},
        {'event': 'agent_done', 'exit_code': 0},
        {'event': 'delegate_reply', 'reply_preview': 'SENT'},
        {'event': 'delegate_exit', 'total_ms': 8000, 'final_output': 'SENT'},
    ]
    interactions = na.parse_router_interactions(events)
    (p if len(interactions) == 1 else f)(f'single interaction parsed (got {len(interactions)})')
    i = interactions[0]
    (p if i['project'] == 'shaadibot' else f)(f'project_match captured (got {i["project"]})')
    (p if i['prompt_bytes'] == 1200 else f)(f'prompt_bytes captured (got {i["prompt_bytes"]})')
    (p if i['exit_code'] == 0 else f)(f'exit_code captured (got {i["exit_code"]})')
    (p if i['total_ms'] == 8000 else f)(f'total_ms captured (got {i["total_ms"]})')
    (p if i['has_reply'] is True else f)(f'has_reply=True when SENT in final_output')
    (p if i['issues'] == [] else f)(f'no issues on clean interaction (got {i["issues"]})')

    # SENT missing from final_output → no_reply
    events2 = [
        {'event': 'delegate_recv', 'ts': 'T2', 'msg_preview': 'test', 'msg_len': 4},
        {'event': 'delegate_exit', 'total_ms': 3000, 'final_output': 'something else'},
    ]
    i2 = na.parse_router_interactions(events2)[0]
    (p if i2['has_reply'] is False else f)('has_reply=False when SENT missing from final_output')

    # Unclosed interaction (no delegate_exit)
    events3 = [
        {'event': 'delegate_recv', 'ts': 'T3', 'msg_preview': 'hi', 'msg_len': 2},
        {'event': 'project_match', 'project': 'foo'},
    ]
    i3 = na.parse_router_interactions(events3)[0]
    (p if any(x[0] == 'no_exit' for x in i3['issues']) else f)('unclosed interaction: no_exit issue added')

    # Concurrent: second delegate_recv before delegate_exit closes first
    events4 = [
        {'event': 'delegate_recv', 'ts': 'T4', 'msg_preview': 'a', 'msg_len': 1},
        {'event': 'delegate_recv', 'ts': 'T5', 'msg_preview': 'b', 'msg_len': 1},
        {'event': 'delegate_exit', 'total_ms': 1000, 'final_output': 'SENT'},
    ]
    ints4 = na.parse_router_interactions(events4)
    (p if len(ints4) == 2 else f)(f'two interactions when second recv arrives (got {len(ints4)})')
    (p if any(x[0] == 'no_exit' for x in ints4[0]['issues']) else f)('first interaction gets no_exit issue')

    # lock_blocked event
    events5 = [
        {'event': 'delegate_recv', 'ts': 'T6', 'msg_preview': 'c', 'msg_len': 1},
        {'event': 'lock_blocked'},
        {'event': 'delegate_exit', 'total_ms': 100, 'final_output': 'SENT'},
    ]
    i5 = na.parse_router_interactions(events5)[0]
    (p if any(x[0] == 'lock_blocked' for x in i5['issues']) else f)('lock_blocked issue captured')

    # stale_lock_broken event
    events6 = [
        {'event': 'delegate_recv', 'ts': 'T7', 'msg_preview': 'd', 'msg_len': 1},
        {'event': 'stale_lock_broken'},
        {'event': 'delegate_exit', 'total_ms': 100, 'final_output': 'SENT'},
    ]
    i6 = na.parse_router_interactions(events6)[0]
    (p if any(x[0] == 'stale_lock' for x in i6['issues']) else f)('stale_lock issue captured')

    # stdout_forward event
    events7 = [
        {'event': 'delegate_recv', 'ts': 'T8', 'msg_preview': 'e', 'msg_len': 1},
        {'event': 'stdout_forward'},
        {'event': 'delegate_exit', 'total_ms': 100, 'final_output': 'SENT'},
    ]
    i7 = na.parse_router_interactions(events7)[0]
    (p if any(x[0] == 'stdout_forward' for x in i7['issues']) else f)('stdout_forward issue captured')

    # stop_signal_detected
    events8 = [
        {'event': 'delegate_recv', 'ts': 'T9', 'msg_preview': 'f', 'msg_len': 1},
        {'event': 'stop_signal_detected'},
        {'event': 'delegate_exit', 'total_ms': 100, 'final_output': 'SENT'},
    ]
    i8 = na.parse_router_interactions(events8)[0]
    (p if i8['has_stop_signal'] is True else f)('stop_signal_detected sets has_stop_signal')

# ── 5. check_interaction ────────────────────────────────────────────────────
print('\n5. check_interaction')
if na:
    def make_interaction(**kwargs):
        base = {
            'ts': 'T', 'msg_preview': 'test', 'msg_len': 10,
            'project': 'proj', 'prompt_bytes': 1000, 'exit_code': 0,
            'total_ms': 5000, 'has_reply': True,
            'has_failure_event': False, 'has_stop_signal': False, 'issues': [],
        }
        base.update(kwargs)
        return base

    # Clean interaction: no issues
    clean = make_interaction()
    na.check_interaction(clean)
    (p if clean['issues'] == [] else f)(f'clean interaction: no issues (got {clean["issues"]})')

    # exit_nonzero
    bad_exit = make_interaction(exit_code=1)
    na.check_interaction(bad_exit)
    (p if any(x[0] == 'exit_nonzero' for x in bad_exit['issues']) else f)('exit_nonzero flagged')

    # no_reply
    no_reply = make_interaction(has_reply=False)
    na.check_interaction(no_reply)
    (p if any(x[0] == 'no_reply' for x in no_reply['issues']) else f)('no_reply flagged')

    # failure_detected suppresses no_reply
    failure = make_interaction(has_reply=False, has_failure_event=True)
    na.check_interaction(failure)
    issue_keys = [x[0] for x in failure['issues']]
    (p if 'failure_detected' in issue_keys else f)('failure_detected issue present')
    (p if 'no_reply' not in issue_keys else f)('no_reply suppressed when failure_detected')

    # near_timeout (>=110000ms)
    near_to = make_interaction(total_ms=115000)
    na.check_interaction(near_to)
    (p if any(x[0] == 'near_timeout' for x in near_to['issues']) else f)('near_timeout at 115s')
    (p if any(x[1] == 'high' for x in near_to['issues'] if x[0] == 'near_timeout') else f)('near_timeout severity=high')

    # slow (>=60000ms, <110000ms)
    slow = make_interaction(total_ms=75000)
    na.check_interaction(slow)
    (p if any(x[0] == 'slow' for x in slow['issues']) else f)('slow at 75s')
    (p if any(x[1] == 'medium' for x in slow['issues'] if x[0] == 'slow') else f)('slow severity=medium')

    # Not slow at 59s
    not_slow = make_interaction(total_ms=59000)
    na.check_interaction(not_slow)
    (p if not any(x[0] == 'slow' for x in not_slow['issues']) else f)('no slow at 59s')

    # tiny_prompt
    tiny = make_interaction(prompt_bytes=500)
    na.check_interaction(tiny)
    (p if any(x[0] == 'tiny_prompt' for x in tiny['issues']) else f)('tiny_prompt flagged at 500B')
    (p if any(x[1] == 'low' for x in tiny['issues'] if x[0] == 'tiny_prompt') else f)('tiny_prompt severity=low')

    # 0 prompt_bytes not flagged (likely no prompt_ready event)
    zero_prompt = make_interaction(prompt_bytes=0)
    na.check_interaction(zero_prompt)
    (p if not any(x[0] == 'tiny_prompt' for x in zero_prompt['issues']) else f)('0 prompt_bytes not flagged as tiny')

    # user_stopped: only user_stopped issue, no other checks
    stopped = make_interaction(has_stop_signal=True, exit_code=1, has_reply=False)
    na.check_interaction(stopped)
    keys = [x[0] for x in stopped['issues']]
    (p if 'user_stopped' in keys else f)('user_stopped issue added')
    (p if 'exit_nonzero' not in keys else f)('exit_nonzero skipped when user_stopped')
    (p if 'no_reply' not in keys else f)('no_reply skipped when user_stopped')

# ── 6. parse_gateway_stats ──────────────────────────────────────────────────
print('\n6. parse_gateway_stats')
if na:
    gw_events = [
        {'event': 'ask_received', 'sid': 'a1'},
        {'event': 'ask_received', 'sid': 'a2'},
        {'event': 'data_post_received'},
        {'event': 'data_post_received'},
        {'event': 'request_done', 'sid': 'a1', 'status': 200, 'duration_ms': 3000},
        {'event': 'request_done', 'sid': 'a2', 'status': 500, 'duration_ms': 1000},
    ]
    stats = na.parse_gateway_stats(gw_events)
    (p if stats['ask_requests'] == 2 else f)(f'ask_requests=2 (got {stats["ask_requests"]})')
    (p if stats['ask_errors'] == 1 else f)(f'ask_errors=1 (got {stats["ask_errors"]})')
    (p if stats['data_posts'] == 2 else f)(f'data_posts=2 (got {stats["data_posts"]})')
    (p if stats['avg_duration_ms'] == 2000 else f)(f'avg_duration_ms=2000 (got {stats["avg_duration_ms"]})')

    # Empty events
    empty_stats = na.parse_gateway_stats([])
    (p if empty_stats['ask_requests'] == 0 else f)('empty events: ask_requests=0')
    (p if empty_stats['avg_duration_ms'] is None else f)('empty events: avg_duration_ms=None')

# ── 7. format_report ────────────────────────────────────────────────────────
print('\n7. format_report')
if na:
    def make_i_with_issues(issues):
        return {
            'ts': 'T', 'msg_preview': 'test msg', 'project': 'proj',
            'prompt_bytes': 1000, 'exit_code': 0, 'total_ms': 5000,
            'has_reply': True, 'has_failure_event': False, 'has_stop_signal': False,
            'issues': issues,
        }

    gw_stats_empty = {'ask_requests': 0, 'ask_errors': 0, 'data_posts': 0, 'avg_duration_ms': None}

    # All clean → ✅ status
    clean_report = na.format_report('2026-06-13', [make_i_with_issues([])], gw_stats_empty)
    (p if '✅' in clean_report else f)('clean interactions: ✅ status icon')
    (p if 'No issues found.' in clean_report else f)('clean: "No issues found." present')
    (p if '-# sent by claude' in clean_report else f)('watermark present')

    # High issues → ⚠️ when <=2 high
    one_high = na.format_report('2026-06-13', [make_i_with_issues([('no_reply', 'high', 'x')])], gw_stats_empty)
    (p if '⚠️' in one_high else f)('1 high issue: ⚠️ status')

    # >2 high → 🔴
    highs = [make_i_with_issues([('no_reply', 'high', 'x')]) for _ in range(3)]
    many_high = na.format_report('2026-06-13', highs, gw_stats_empty)
    (p if '🔴' in many_high else f)('3+ high issues: 🔴 status')

    # No interactions
    no_int = na.format_report('2026-06-13', [], gw_stats_empty)
    (p if 'no interactions' in no_int else f)('zero interactions: "no interactions" in report')

    # Gateway stats in report
    gw_stats = {'ask_requests': 5, 'ask_errors': 1, 'data_posts': 3, 'avg_duration_ms': 2500}
    gw_report = na.format_report('2026-06-13', [], gw_stats)
    (p if 'Gateway /ask: 5 requests' in gw_report else f)('gateway ask count in report')
    (p if '1 errors' in gw_report else f)('gateway error count in report')
    (p if '2500ms' in gw_report else f)('gateway avg duration in report')
    (p if 'Gateway /data: 3 posts' in gw_report else f)('gateway data posts in report')

    # Issue line format
    issue_i = make_i_with_issues([('no_reply', 'high', 'x'), ('slow', 'medium', 'y')])
    issue_report = na.format_report('2026-06-13', [issue_i], gw_stats_empty)
    (p if '[proj]' in issue_report else f)('issue line has [project]')
    (p if 'no_reply' in issue_report else f)('issue line has issue code')
    (p if 'slow' in issue_report else f)('issue line has second issue code')

    # Failed count
    failed_i = make_i_with_issues([('no_reply', 'high', 'x')])
    failed_report = na.format_report('2026-06-13', [failed_i], gw_stats_empty)
    (p if 'failed' in failed_report else f)('failed count present in report')

# ── 8. load_gateway_token ───────────────────────────────────────────────────
print('\n8. load_gateway_token')
if na:
    with tempfile.TemporaryDirectory() as td:
        config_path = Path(td) / 'openclaw.json'
        config_path.write_text(json.dumps({'gateway': {'auth': {'token': 'test-tok-123'}}}), encoding='utf-8')

        # Monkey-patch Path.home to return td
        orig_home = Path.home
        try:
            Path.home = staticmethod(lambda: Path(td))
            # Recreate the .openclaw/openclaw.json expected structure
            dot = Path(td) / '.openclaw'
            dot.mkdir()
            (dot / 'openclaw.json').write_text(
                json.dumps({'gateway': {'auth': {'token': 'test-tok-123'}}}), encoding='utf-8'
            )
            tok = na.load_gateway_token()
            (p if tok == 'test-tok-123' else f)(f'load_gateway_token reads token (got {tok})')
        finally:
            Path.home = orig_home

    # Missing file returns None
    import unittest.mock as mock
    with mock.patch('pathlib.Path.home', return_value=Path('/nonexistent/path/xyz')):
        tok_none = na.load_gateway_token()
        (p if tok_none is None else f)(f'load_gateway_token returns None when config missing (got {tok_none})')

# ── 9. phase2_quality_score ─────────────────────────────────────────────────
print('\n9. phase2_quality_score')
if na:
    # No flagged → returns None immediately (no gateway call)
    clean_i = [make_i_with_issues([])]
    result = na.phase2_quality_score('tok', clean_i, '2026-06-13')
    (p if result is None else f)(f'phase2: no flagged → None (got {result})')

    # user_stopped only → not flagged for quality review
    stopped_i = [make_i_with_issues([('user_stopped', 'low', 'x')])]
    result2 = na.phase2_quality_score('tok', stopped_i, '2026-06-13')
    (p if result2 is None else f)(f'phase2: user_stopped only → None (got {result2})')

    # high-severity non-user_stopped → would call gateway (we just check it builds a prompt)
    # Patch call_gateway to capture what was called
    import unittest.mock as mock
    with mock.patch.object(na, 'call_gateway', return_value='mock-quality-response') as cg:
        flagged_i = [make_i_with_issues([('no_reply', 'high', 'x')])]
        flagged_i[0]['msg_preview'] = 'deploy the app'
        flagged_i[0]['project'] = 'dairy'
        result3 = na.phase2_quality_score('tok', flagged_i, '2026-06-13')
        (p if cg.called else f)('phase2: call_gateway called for high-severity issue')
        (p if result3 == 'mock-quality-response' else f)(f'phase2: gateway response forwarded (got {result3})')
        call_args = cg.call_args[0]
        prompt_text = call_args[1]
        (p if 'deploy the app' in prompt_text else f)('phase2: prompt includes msg_preview')
        (p if 'dairy' in prompt_text else f)('phase2: prompt includes project name')
        (p if 'no_reply' in prompt_text else f)('phase2: prompt includes issue code')

# ── 10. phase3_optimization ──────────────────────────────────────────────────
print('\n10. phase3_optimization')
if na:
    gw_stats_none = {'ask_requests': 0, 'ask_errors': 0, 'data_posts': 0, 'avg_duration_ms': None}

    # No interactions → None
    result_empty = na.phase3_optimization('tok', [], gw_stats_none, '2026-06-13')
    (p if result_empty is None else f)(f'phase3: no interactions → None (got {result_empty})')

    # Interactions but no high/slow → None
    clean_ints = [make_i_with_issues([])]
    result_clean = na.phase3_optimization('tok', clean_ints, gw_stats_none, '2026-06-13')
    (p if result_clean is None else f)(f'phase3: clean interactions → None (got {result_clean})')

    # High-severity issues → call gateway
    with mock.patch.object(na, 'call_gateway', return_value='mock-suggestions') as cg3:
        high_ints = [make_i_with_issues([('no_reply', 'high', 'x')])]
        result_high = na.phase3_optimization('tok', high_ints, gw_stats_none, '2026-06-13')
        (p if cg3.called else f)('phase3: call_gateway called when high issues present')
        (p if result_high == 'mock-suggestions' else f)(f'phase3: response forwarded (got {result_high})')
        prompt3 = cg3.call_args[0][1]
        (p if 'Total interactions' in prompt3 else f)('phase3: prompt has interaction count')
        (p if 'High-severity' in prompt3 else f)('phase3: prompt has high-severity count')

    # Slow interactions → call gateway even without high
    slow_i = make_i_with_issues([])
    slow_i['total_ms'] = 70000
    with mock.patch.object(na, 'call_gateway', return_value='mock-slow') as cg4:
        result_slow = na.phase3_optimization('tok', [slow_i], gw_stats_none, '2026-06-13')
        (p if cg4.called else f)('phase3: call_gateway called when slow interactions present')

# ── 11. Source code structure checks ─────────────────────────────────────────
print('\n11. Source code structure')
(p if 'def load_jsonl' in src else f)('load_jsonl function defined')
(p if 'def parse_router_interactions' in src else f)('parse_router_interactions function defined')
(p if 'def check_interaction' in src else f)('check_interaction function defined')
(p if 'def parse_gateway_stats' in src else f)('parse_gateway_stats function defined')
(p if 'def format_report' in src else f)('format_report function defined')
(p if 'def load_gateway_token' in src else f)('load_gateway_token function defined')
(p if 'def call_gateway' in src else f)('call_gateway function defined')
(p if 'def phase2_quality_score' in src else f)('phase2_quality_score function defined')
(p if 'def phase3_optimization' in src else f)('phase3_optimization function defined')
(p if 'def run_tests' in src else f)('run_tests function defined')
(p if 'def check_file_safety' in src else f)('check_file_safety function defined')
(p if 'def safe_change_cycle' in src else f)('safe_change_cycle function defined')
(p if 'def phase4_autofix' in src else f)('phase4_autofix function defined')
(p if 'def main' in src else f)('main function defined')
(p if 'DISCORD_TARGET' in src else f)('DISCORD_TARGET constant defined')
(p if 'GATEWAY_URL' in src else f)('GATEWAY_URL constant defined')
(p if 'GATEWAY_PROJECT' in src else f)('GATEWAY_PROJECT constant defined')
(p if 'PROTECTED_FILES' in src else f)('PROTECTED_FILES constant defined')
(p if '-# sent by claude' in src else f)('watermark in source')
(p if "if __name__ == '__main__'" in src else f)("__main__ guard present")

# ── 12. Severity levels ───────────────────────────────────────────────────────
print('\n12. Severity levels')
(p if "'high'" in src else f)("'high' severity used")
(p if "'medium'" in src else f)("'medium' severity used")
(p if "'low'" in src else f)("'low' severity used")

# Check specific severity assignments in source
(p if "near_timeout', 'high'" in src else f)("near_timeout is high severity")
(p if "slow', 'medium'" in src else f)("slow is medium severity")
(p if "tiny_prompt', 'low'" in src else f)("tiny_prompt is low severity")
(p if "no_reply', 'high'" in src else f)("no_reply is high severity")
(p if "exit_nonzero', 'high'" in src else f)("exit_nonzero is high severity")

# ── 13. run_tests ────────────────────────────────────────────────────────────
print('\n13. run_tests')
if na:
    import unittest.mock as mock
    (p if hasattr(na, 'run_tests') else f)('run_tests function exists')

    # Parses "N passed, M failed" from stdout
    mock_result = mock.MagicMock()
    mock_result.stdout = 'Results: 10 passed, 0 failed\n'
    mock_result.stderr = ''
    with mock.patch('subprocess.run', return_value=mock_result):
        rt = na.run_tests()
        (p if isinstance(rt, tuple) and len(rt) == 2 else f)(f'run_tests returns 2-tuple (got {rt})')
        (p if rt == (10, 0) else f)(f'run_tests parses 10 passed 0 failed (got {rt})')

    # Returns (-1,-1) on subprocess error
    with mock.patch('subprocess.run', side_effect=Exception('proc error')):
        rt_err = na.run_tests()
        (p if rt_err == (-1, -1) else f)(f'run_tests returns (-1,-1) on error (got {rt_err})')

    # Handles zero-match stdout gracefully
    mock_result2 = mock.MagicMock()
    mock_result2.stdout = 'no summary line here'
    mock_result2.stderr = ''
    with mock.patch('subprocess.run', return_value=mock_result2):
        rt_zero = na.run_tests()
        (p if rt_zero == (0, 0) else f)(f'run_tests returns (0,0) when no summary line (got {rt_zero})')


# ── 14. check_file_safety ─────────────────────────────────────────────────────
print('\n14. check_file_safety')
if na:
    import unittest.mock as mock
    import tempfile
    (p if hasattr(na, 'check_file_safety') else f)('check_file_safety function exists')
    (p if hasattr(na, 'PROTECTED_FILES') else f)('PROTECTED_FILES constant exists')
    (p if isinstance(na.PROTECTED_FILES, (set, frozenset)) else f)('PROTECTED_FILES is a set')

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        (td_path / 'bin').mkdir()

        # Non-protected file
        safe_file = td_path / 'bin' / 'some-script.py'
        safe_file.write_text('# safe\n', encoding='utf-8')
        with mock.patch.object(na, 'REPO_DIR', td_path):
            is_p, info = na.check_file_safety(safe_file)
            (p if is_p is False else f)(f'non-protected file: is_protected=False (got {is_p})')
            (p if info is None else f)(f'non-protected file: info=None (got {info})')

        # Protected file
        bot_file = td_path / 'bin' / 'discord-bot.py'
        bot_file.write_text('# bot\n' * 5, encoding='utf-8')
        with mock.patch.object(na, 'REPO_DIR', td_path):
            with mock.patch.object(na, 'PROTECTED_FILES', {'bin/discord-bot.py'}):
                is_p2, info2 = na.check_file_safety(bot_file)
                (p if is_p2 is True else f)(f'discord-bot.py: is_protected=True (got {is_p2})')
                (p if info2 is not None else f)(f'discord-bot.py: info string returned (got {info2})')
                (p if 'discord-bot.py' in (info2 or '') else f)('info string contains filename')


# ── 15. safe_change_cycle ─────────────────────────────────────────────────────
print('\n15. safe_change_cycle')
if na:
    import unittest.mock as mock
    import tempfile
    (p if hasattr(na, 'safe_change_cycle') else f)('safe_change_cycle function exists')

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        (td_path / 'bin').mkdir()
        (td_path / 'tests').mkdir()

        target = td_path / 'bin' / 'delegate.py'
        target.write_text('TIMEOUT = 100\n# other code\n', encoding='utf-8')

        test_file = td_path / 'tests' / 'test_nightly_audit.py'
        test_file.write_text('# tests\n# ── Summary ──\nprint("0 passed, 0 failed")\n', encoding='utf-8')

        with mock.patch.object(na, 'REPO_DIR', td_path):
            with mock.patch.object(na, 'PROTECTED_FILES', set()):

                # Case 1: baseline tests fail → abort immediately
                with mock.patch.object(na, 'run_tests', return_value=(5, 2)):
                    ok, msg = na.safe_change_cycle('bump timeout', target, 'TIMEOUT = 100', 'TIMEOUT = 120')
                    (p if ok is False else f)(f'safe_change_cycle: aborts on baseline failure (got ok={ok})')
                    (p if 'Baseline' in msg or 'failing' in msg.lower() or 'baseline' in msg.lower() else f)(
                        f'safe_change_cycle: abort message mentions baseline (got: {msg})')
                    # File must be unchanged
                    (p if 'TIMEOUT = 100' in target.read_text() else f)(
                        'file not modified when baseline fails')

                # Case 2: post-change tests fail → revert file
                call_seq = [0]
                def run_tests_revert():
                    call_seq[0] += 1
                    return (10, 0) if call_seq[0] == 1 else (8, 2)
                with mock.patch.object(na, 'run_tests', side_effect=run_tests_revert):
                    with mock.patch('subprocess.run'):
                        ok2, msg2 = na.safe_change_cycle('bump timeout', target, 'TIMEOUT = 100', 'TIMEOUT = 120')
                        (p if ok2 is False else f)(f'safe_change_cycle: fails when post-change tests break (ok={ok2})')
                        (p if 'TIMEOUT = 100' in target.read_text() else f)(
                            'safe_change_cycle: file reverted after test failure')

                # Case 3: happy path — change applied, commit called
                with mock.patch.object(na, 'run_tests', return_value=(10, 0)):
                    with mock.patch('subprocess.run') as mock_sp:
                        ok3, msg3 = na.safe_change_cycle('bump timeout', target, 'TIMEOUT = 100', 'TIMEOUT = 130')
                        (p if ok3 is True else f)(f'safe_change_cycle: succeeds on happy path (ok={ok3}, msg={msg3})')
                        (p if 'TIMEOUT = 130' in target.read_text() else f)(
                            'safe_change_cycle: change applied on success')
                        git_calls = [str(c) for c in mock_sp.call_args_list]
                        (p if any('commit' in c for c in git_calls) else f)(
                            'safe_change_cycle: git commit called')
                        (p if any('push' in c for c in git_calls) else f)(
                            'safe_change_cycle: git push called')

                # Case 4: protected file with large delta → skip
                with mock.patch.object(na, 'PROTECTED_FILES', {'bin/delegate.py'}):
                    target.write_text('TIMEOUT = 130\n# other code\n', encoding='utf-8')
                    big_new = 'TIMEOUT = 130\n' + 'x' * 300
                    ok4, msg4 = na.safe_change_cycle('big change', target, 'TIMEOUT = 130', big_new)
                    (p if ok4 is False else f)(f'safe_change_cycle: protected file big delta → False (ok={ok4})')
                    (p if 'skipping' in msg4.lower() or 'skip' in msg4.lower() else f)(
                        f'safe_change_cycle: protected skip message (got: {msg4})')


# ── 16. phase4_autofix ────────────────────────────────────────────────────────
print('\n16. phase4_autofix')
if na:
    import unittest.mock as mock
    import tempfile
    (p if hasattr(na, 'phase4_autofix') else f)('phase4_autofix function exists')

    # None/empty suggestions → None
    (p if na.phase4_autofix('tok', None, '2026-06-14') is None else f)(
        'phase4_autofix: None suggestions → None')
    (p if na.phase4_autofix('tok', '', '2026-06-14') is None else f)(
        'phase4_autofix: empty suggestions → None')

    with tempfile.TemporaryDirectory() as td3:
        td3_path = Path(td3)
        (td3_path / 'bin').mkdir()
        agent_file = td3_path / 'bin' / 'agent-smart.py'
        agent_file.write_text('THRESHOLD = 400\n', encoding='utf-8')

        valid_patch = json.dumps({
            'file': 'bin/agent-smart.py',
            'desc': 'increase compaction threshold',
            'old': 'THRESHOLD = 400',
            'new': 'THRESHOLD = 500',
            'test': None,
        })

        # Gateway returns valid patch → safe_change_cycle called
        with mock.patch.object(na, 'call_gateway', return_value=valid_patch):
            with mock.patch.object(na, 'REPO_DIR', td3_path):
                with mock.patch.object(na, 'safe_change_cycle',
                                       return_value=(True, 'Applied: increase compaction threshold')) as sc:
                    result = na.phase4_autofix('tok', 'increase threshold for perf', '2026-06-14')
                    (p if sc.called else f)('phase4_autofix: calls safe_change_cycle for valid patch')
                    (p if result is not None and 'OK' in result else f)(
                        f'phase4_autofix: result contains OK (got {result})')

    # Incomplete patch → SKIP
    bad_patch = json.dumps({'file': 'bin/agent-smart.py', 'desc': 'missing old/new'})
    with mock.patch.object(na, 'call_gateway', return_value=bad_patch):
        with mock.patch.object(na, 'REPO_DIR', Path('/nonexistent/fake')):
            r_bad = na.phase4_autofix('tok', 'some suggestion', '2026-06-14')
            (p if r_bad is not None and 'SKIP' in r_bad else f)(
                f'phase4_autofix: incomplete patch → SKIP (got {r_bad})')

    # File not found → SKIP
    missing_patch = json.dumps({
        'file': 'bin/does-not-exist.py',
        'desc': 'change something',
        'old': 'FOO',
        'new': 'BAR',
        'test': None,
    })
    with mock.patch.object(na, 'call_gateway', return_value=missing_patch):
        with mock.patch.object(na, 'REPO_DIR', Path('/nonexistent/fake')):
            r_miss = na.phase4_autofix('tok', 'some suggestion', '2026-06-14')
            (p if r_miss is not None and 'SKIP' in r_miss else f)(
                f'phase4_autofix: missing file → SKIP (got {r_miss})')

    # Gateway returns None → None
    with mock.patch.object(na, 'call_gateway', return_value=None):
        r_none = na.phase4_autofix('tok', 'suggestions here', '2026-06-14')
        (p if r_none is None else f)(f'phase4_autofix: gateway returns None → None (got {r_none})')


# ── Summary ──────────────────────────────────────────────────────────────────
print()
print('=' * 50)
print(f'Results: {PASS} passed, {FAIL} failed')
sys.exit(0 if FAIL == 0 else 1)
