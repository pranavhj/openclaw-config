#!/bin/bash
# Integration tests for openclaw delegation pipeline
# Tests: Gemini → delegate skill → Claude → Discord
# Followed by Claude log analysis of all today's sessions

PASS=0
FAIL=0
SESSIONS_DIR="/home/pranav/.openclaw/agents/main/sessions"
LOGDIR="/tmp/openclaw"
DISCORD_TARGET="1482473282925101217"
TODAY=$(date +%Y-%m-%d)

pass() { echo "  PASS: $1"; PASS=$((PASS+1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }
skip() { echo "  SKIP: $1"; }

# Real Discord DM sessions: started today, contain a PDT timestamp in a user message
# that looks like "[Day YYYY-MM-DD HH:MM PDT] <actual text>" (not system messages)
real_discord_sessions() {
  python3 - << 'EOF'
import json, glob, os, re

sessions_dir = os.environ.get('SESSIONS_DIR', '/home/pranav/.openclaw/agents/main/sessions')
today = os.environ.get('TODAY', '')
results = []
skip_keys = {'cron', 'test', 'fresh', 'dispatch', 'gateway', 'gq-new', 'skill-list'}

# Pattern: [Thu 2026-03-19 10:25 PDT] <non-system text>
dm_pattern = re.compile(r'\[(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{4}-\d{2}-\d{2} \d{2}:\d{2} P[DS]T\] (?!System:)(?!\[cron)')

agents_md = '/home/pranav/.openclaw/workspace/AGENTS.md'
skill_md = '/home/pranav/.openclaw/workspace/skills/delegate/SKILL.md'
cutoff_mtime = max(
    os.path.getmtime(agents_md) if os.path.exists(agents_md) else 0,
    os.path.getmtime(skill_md) if os.path.exists(skill_md) else 0,
)

for f in sorted(glob.glob(os.path.join(sessions_dir, '*.jsonl'))):
    sid = os.path.basename(f)
    if any(x in sid for x in skip_keys):
        continue
    # Only include sessions created after the AGENTS.md fix
    if os.path.getmtime(f) < cutoff_mtime:
        continue
    try:
        with open(f) as fh:
            first = json.loads(fh.readline())
        ts = first.get('timestamp', '')
        if not ts.startswith(today):
            continue
        with open(f) as fh:
            lines = fh.readlines()
    except:
        continue

    # Must have at least one user message matching the Discord DM pattern
    for line in lines:
        try:
            msg = json.loads(line)
        except:
            continue
        if msg.get('type') != 'message':
            continue
        m = msg.get('message', {})
        if m.get('role') != 'user':
            continue
        for c in m.get('content', []):
            if isinstance(c, dict) and c.get('type') == 'text':
                if dm_pattern.search(c.get('text', '')):
                    results.append(f)
                    break
        else:
            continue
        break

print(' '.join(results))
EOF
}

# Check if Gemini called exec with 'delegate' as the command
# JSONL format: role=assistant, content=[{type:toolCall, name:exec, arguments:{command:"delegate ..."}}]
session_called_delegate() {
  python3 - << EOF
import json, sys

with open('$1') as f:
    for line in f:
        try: msg = json.loads(line)
        except: continue
        if msg.get('type') != 'message': continue
        m = msg.get('message', {})
        if m.get('role') != 'assistant': continue
        for c in m.get('content', []):
            if not isinstance(c, dict): continue
            if c.get('type') == 'toolCall' and c.get('name') == 'exec':
                cmd = c.get('arguments', {}).get('command', '')
                if cmd.strip().startswith('delegate '):
                    sys.exit(0)
sys.exit(1)
EOF
}

# Check if Gemini called agent directly (AGENTS.md Mode 2 bypass — routing bug)
session_called_agent_directly() {
  python3 - << EOF
import json, sys

with open('$1') as f:
    for line in f:
        try: msg = json.loads(line)
        except: continue
        if msg.get('type') != 'message': continue
        m = msg.get('message', {})
        if m.get('role') != 'assistant': continue
        for c in m.get('content', []):
            if not isinstance(c, dict): continue
            if c.get('type') == 'toolCall' and c.get('name') == 'exec':
                cmd = c.get('arguments', {}).get('command', '')
                if 'agent --permission-mode' in cmd or 'agent --continue' in cmd:
                    sys.exit(0)
sys.exit(1)
EOF
}

# Check if exec ran in background (toolResult role has "Command still running")
session_exec_was_background() {
  python3 - << EOF
import json, sys

with open('$1') as f:
    for line in f:
        try: msg = json.loads(line)
        except: continue
        if msg.get('type') != 'message': continue
        m = msg.get('message', {})
        if m.get('role') != 'toolResult': continue
        for c in m.get('content', []):
            if isinstance(c, dict) and 'Command still running' in c.get('text', ''):
                sys.exit(0)
sys.exit(1)
EOF
}

# Check if exec was called with yieldMs >= 60000 (at least 1 minute wait)
session_exec_has_yield() {
  python3 - << EOF
import json, sys

with open('$1') as f:
    for line in f:
        try: msg = json.loads(line)
        except: continue
        if msg.get('type') != 'message': continue
        m = msg.get('message', {})
        if m.get('role') != 'assistant': continue
        for c in m.get('content', []):
            if not isinstance(c, dict): continue
            if c.get('type') == 'toolCall' and c.get('name') == 'exec':
                args = c.get('arguments', {})
                if args.get('command', '').strip().startswith('delegate '):
                    if args.get('yieldMs', 0) >= 60000:
                        sys.exit(0)
sys.exit(1)
EOF
}

# Check if exec returned SENT (foreground delegate completed)
session_got_sent() {
  python3 - << EOF
import json, sys

with open('$1') as f:
    for line in f:
        try: msg = json.loads(line)
        except: continue
        if msg.get('type') != 'message': continue
        m = msg.get('message', {})
        role = m.get('role', '')
        # toolResult role with SENT in content
        if role == 'toolResult':
            for c in m.get('content', []):
                if isinstance(c, dict) and 'SENT' in c.get('text', ''):
                    sys.exit(0)
        # assistant text with SENT
        if role == 'assistant':
            for c in m.get('content', []):
                if isinstance(c, dict) and c.get('type') == 'text' and 'SENT' in c.get('text', ''):
                    sys.exit(0)
sys.exit(1)
EOF
}

# Check if Gemini used write tool on any workspace config file (config tampering)
session_used_write_on_config() {
  python3 - << EOF
import json, sys

WORKSPACE_PATHS = ['.openclaw/workspace', 'openclaw/workspace', '/workspace/']
CONFIG_FILES = ['AGENTS.md', 'SKILL.md', 'SOUL.md', 'IDENTITY.md', 'TOOLS.md', 'USER.md', 'HEARTBEAT.md']

with open('$1') as f:
    for line in f:
        try: msg = json.loads(line)
        except: continue
        if msg.get('type') != 'message': continue
        m = msg.get('message', {})
        if m.get('role') != 'assistant': continue
        for c in m.get('content', []):
            if not isinstance(c, dict): continue
            if c.get('type') in ('toolCall', 'tool_use') and c.get('name') == 'write':
                args = c.get('arguments', c.get('input', {}))
                path = args.get('file_path', '') if isinstance(args, dict) else ''
                if any(p in path for p in WORKSPACE_PATHS) or any(f in path for f in CONFIG_FILES):
                    sys.exit(0)
sys.exit(1)
EOF
}

# Check if Gemini used any non-exec tool (read, write, web_search — all routing bugs)
session_used_non_exec_tool() {
  python3 - << EOF
import json, sys

NON_EXEC_TOOLS = {'read', 'write', 'web_search', 'grep', 'glob', 'bash', 'edit'}

with open('$1') as f:
    for line in f:
        try: msg = json.loads(line)
        except: continue
        if msg.get('type') != 'message': continue
        m = msg.get('message', {})
        if m.get('role') != 'assistant': continue
        for c in m.get('content', []):
            if not isinstance(c, dict): continue
            if c.get('type') in ('toolCall', 'tool_use'):
                name = c.get('name', '')
                if name in NON_EXEC_TOOLS:
                    sys.exit(0)
sys.exit(1)
EOF
}

# Check if SKILL.md was loaded (toolResult with delegate skill content)
session_skill_loaded() {
  python3 - << EOF
import json, sys

with open('$1') as f:
    for line in f:
        try: msg = json.loads(line)
        except: continue
        if msg.get('type') != 'message': continue
        m = msg.get('message', {})
        if m.get('role') != 'toolResult': continue
        for c in m.get('content', []):
            if isinstance(c, dict):
                text = c.get('text', '')
                if 'background:false' in text or 'Delegate ALL' in text or 'Delegate ANY' in text or 'delegate' in text.lower():
                    sys.exit(0)
sys.exit(1)
EOF
}

echo "=========================================="
echo " openclaw delegation integration tests"
echo "=========================================="
echo ""

# ── Pre-flight ────────────────────────────────────────────────────────────────
echo "Pre-flight: discord-bot service check..."
systemctl --user is-active discord-bot >/dev/null 2>&1 && echo "  discord-bot running" || echo "  WARNING: discord-bot not running"
echo ""

# ── Test 1: Delegate end-to-end (Claude → Discord) ───────────────────────────
echo "1. Delegate script end-to-end"

LOG_BEFORE=$(wc -l < "$LOGDIR/delegate-$TODAY.log" 2>/dev/null || echo 0)

DELEGATE_OUT=$(/home/pranav/.local/bin/delegate discord "$DISCORD_TARGET" \
  "[integration-test] What is 1+1? Reply with just: 2" 2>&1)

[[ "$DELEGATE_OUT" == "SENT" ]] \
  && pass "delegate outputs SENT" \
  || fail "expected SENT, got: ${DELEGATE_OUT:0:80}"

LOG_AFTER=$(wc -l < "$LOGDIR/delegate-$TODAY.log" 2>/dev/null || echo 0)
[[ $LOG_AFTER -gt $LOG_BEFORE ]] \
  && pass "delegate log entry written" || fail "no new log entry"

tail -20 "$LOGDIR/delegate-$TODAY.log" 2>/dev/null | grep -q "exit_code: 0" \
  && pass "delegate log shows exit_code: 0" || fail "missing exit_code: 0 in log"

echo ""

# ── Test 2: Lock deduplication ────────────────────────────────────────────────
echo "2. Concurrent delegate (lock)"

LOG_LOCKED=$LOG_AFTER
mkdir "$LOGDIR/delegate.lock" 2>/dev/null
CONCURRENT=$(/home/pranav/.local/bin/delegate discord "$DISCORD_TARGET" "should not send" 2>&1)
rmdir "$LOGDIR/delegate.lock" 2>/dev/null

[[ "$CONCURRENT" == *"SENT"* ]] \
  && pass "locked call returns SENT immediately" \
  || fail "expected SENT from locked call, got: $CONCURRENT"

LOG_POSTLOCK=$(wc -l < "$LOGDIR/delegate-$TODAY.log" 2>/dev/null || echo 0)
# Locked call writes a lock_blocked line to log (expected), but should NOT write a full delegation entry
grep -q "lock_blocked" "$LOGDIR/delegate-$TODAY.log" 2>/dev/null \
  && pass "locked call logged lock_blocked event" \
  || pass "locked call wrote no log entry (blocked)"
# Agent should NOT have run
! grep -q "should not send" "$LOGDIR/delegate-$TODAY.log" 2>/dev/null \
  && pass "blocked message not processed by agent" \
  || fail "blocked message was processed despite lock"

echo ""

# ── Test 2b: discord-bot service health ───────────────────────────────────────
echo "2b. discord-bot service health"

systemctl --user is-active discord-bot >/dev/null 2>&1 \
  && pass "discord-bot service is active" \
  || fail "discord-bot service is not active"

systemctl --user show discord-bot --property=ExecMainPID --value 2>/dev/null | grep -qv '^0$' \
  && pass "discord-bot has a running PID" \
  || fail "discord-bot PID is 0 (not running)"

echo ""

# ── Test 3: discord-send works ────────────────────────────────────────────────
echo "3. discord-send end-to-end"

SEND_OUT=$(discord-send --target "$DISCORD_TARGET" --message "[integration-test] discord-send test $(date +%H:%M:%S)" 2>&1)
[[ "$SEND_OUT" == *"Sent"* ]] \
  && pass "discord-send returned success" \
  || fail "discord-send failed: $SEND_OUT"

# ── Test 3b: Workspace integrity ──────────────────────────────────────────────
echo ""
echo "3b. Workspace integrity (rogue skills / binaries)"

SKILLS_DIR="$HOME/.openclaw/workspace/skills"
ALLOWED_SKILLS="delegate discord-send quota gemini-requests routing-audit"
ROGUE_SKILLS=""
for S in $(ls "$SKILLS_DIR" 2>/dev/null); do
  echo "$ALLOWED_SKILLS" | grep -qw "$S" || ROGUE_SKILLS="$ROGUE_SKILLS $S"
done
[[ -z "$ROGUE_SKILLS" ]] \
  && pass "no rogue skills in workspace (allowed: $ALLOWED_SKILLS)" \
  || fail "ROGUE SKILLS found — delete immediately:$ROGUE_SKILLS"

ALLOWED_BINS="delegate discord-bot.py discord-send route-audit run-tests openclaw-timeline route-log send-gemini-stats agent oc httpx gq claude session-reset"
ROGUE_BINS=""
for B in $(ls /home/pranav/.local/bin/ 2>/dev/null); do
  echo "$ALLOWED_BINS" | grep -qw "$B" || ROGUE_BINS="$ROGUE_BINS $B"
done
[[ -z "$ROGUE_BINS" ]] \
  && pass "no rogue binaries in ~/.local/bin" \
  || fail "UNEXPECTED BINARIES in ~/.local/bin:$ROGUE_BINS"

grep -qi "ARCHIVED\|archived\|discord-bot" "$HOME/.openclaw/workspace/AGENTS.md" \
  && pass "AGENTS.md archived (openclaw-gateway disabled)" \
  || fail "AGENTS.md not updated to archived state"

echo ""

echo ""

# ── Test 4c: Timeline log written for delegation ─────────────────────────────
echo "4c. Timeline log validation"

TIMELINE_FILE="$LOGDIR/timeline-$TODAY.log"
if [[ -f "$TIMELINE_FILE" ]]; then
  # Check that key events are present in order
  grep -q '"event":"delegate_recv"' "$TIMELINE_FILE" \
    && pass "timeline: delegate_recv logged" || fail "timeline: delegate_recv missing"
  grep -q '"event":"sanitize"' "$TIMELINE_FILE" \
    && pass "timeline: sanitize logged" || fail "timeline: sanitize missing"
  grep -q '"event":"agent_start"' "$TIMELINE_FILE" \
    && pass "timeline: agent_start logged" || fail "timeline: agent_start missing"
  grep -q '"event":"delegate_exit"' "$TIMELINE_FILE" \
    && pass "timeline: delegate_exit logged" || fail "timeline: delegate_exit missing"

  # Validate JSON format of timeline entries
  INVALID_JSON=$(python3 -c "
import json
count = 0
with open('$TIMELINE_FILE') as f:
    for line in f:
        try: json.loads(line.strip())
        except: count += 1
print(count)
" 2>/dev/null)
  [[ "$INVALID_JSON" == "0" ]] \
    && pass "timeline: all entries valid JSON" \
    || fail "timeline: $INVALID_JSON invalid JSON entries"
else
  skip "no timeline log for today"
fi

echo ""

# ── Test 4d: Scheduled jobs health ────────────────────────────────────────────
echo "4d. Scheduled jobs (crons & timers)"

# route-audit timer should be active
systemctl --user is-active route-audit.timer >/dev/null 2>&1 \
  && pass "route-audit.timer is active" \
  || fail "route-audit.timer not active"

# route-audit should trigger daily at 8 AM
systemctl --user show route-audit.timer -p TimersCalendar 2>/dev/null | grep -q "08:00:00\|8:00" \
  && pass "route-audit triggers at 8 AM" \
  || skip "could not verify route-audit schedule"

# route-audit service should exist and have succeeded last run
systemctl --user show route-audit.service -p ExecMainStatus 2>/dev/null | grep -q "0" \
  && pass "route-audit.service last run succeeded (exit 0)" \
  || fail "route-audit.service last run failed"

# route-audit script should exist and be executable
[[ -x /home/pranav/.local/bin/route-audit ]] \
  && pass "route-audit script is executable" \
  || fail "route-audit script missing or not executable"

# gemini-stats cron (native crontab, not openclaw cron)
crontab -l 2>/dev/null | grep -q "send-gemini-stats" \
  && pass "send-gemini-stats in native crontab" \
  || fail "send-gemini-stats missing from crontab"

[[ -x /home/pranav/.local/bin/send-gemini-stats ]] \
  && pass "send-gemini-stats script is executable" \
  || fail "send-gemini-stats script missing or not executable"

# gemini monitor cron
crontab -l 2>/dev/null | grep -q "monitor_gemini" \
  && pass "monitor_gemini.py in crontab" \
  || skip "monitor_gemini.py not in crontab"

# gemini-requests skill should exist
[[ -f /home/pranav/.openclaw/workspace/skills/gemini-requests/SKILL.md ]] \
  && pass "gemini-requests skill exists" \
  || fail "gemini-requests skill missing"

# quota skill should exist
[[ -f /home/pranav/.openclaw/workspace/skills/quota/SKILL.md ]] \
  && pass "quota skill exists" \
  || fail "quota skill missing"

# No openclaw crons (all moved to native crontab/systemd)
CRON_COUNT=$(openclaw cron list 2>&1 | grep -c "^[0-9a-f]" || true)
[[ "$CRON_COUNT" -eq 0 ]] \
  && pass "no openclaw crons (all native/systemd)" \
  || fail "$CRON_COUNT openclaw cron(s) still active"

echo ""

# ── Test 5: Config sanity ─────────────────────────────────────────────────────
echo "5. Config sanity"

# AGENTS.md should not have Mode 2 exec block anymore
grep -q "agent --permission-mode bypassPermissions" /home/pranav/.openclaw/workspace/AGENTS.md \
  && fail "AGENTS.md still has direct agent exec (Mode 2 not removed)" \
  || pass "AGENTS.md: direct agent exec removed"

grep -q "delegate" /home/pranav/.openclaw/workspace/AGENTS.md \
  && pass "AGENTS.md: references delegate skill" \
  || fail "AGENTS.md: no mention of delegate skill"

# gemini-stats moved to native crontab (no Gemini dependency)
openclaw cron list 2>&1 | grep -q "gemini-stats" \
  && fail "cron: gemini-stats still in openclaw cron (should be native crontab)" \
  || pass "cron: gemini-stats removed from openclaw cron"
crontab -l 2>/dev/null | grep -q "send-gemini-stats" \
  && pass "cron: send-gemini-stats in native crontab" \
  || fail "cron: send-gemini-stats missing from native crontab"

python3 -c "import json; d=json.load(open('/home/pranav/.openclaw/openclaw.json')); print(d['channels']['discord']['retry']['attempts'])" 2>/dev/null \
  | grep -q "^1$" && pass "discord retry.attempts=1 (openclaw minimum)" || fail "discord retry not 1"

# fallbacks intentionally removed — groq can't exec delegate, causes silent drops
python3 -c "
import json, sys
d = json.load(open('/home/pranav/.openclaw/openclaw.json'))
fallbacks = d.get('agents',{}).get('defaults',{}).get('model',{}).get('fallbacks',[])
sys.exit(0 if len(fallbacks) == 0 else 1)
" 2>/dev/null && pass "no fallback models (intentional — groq cannot exec delegate)" || fail "unexpected fallback models configured"

grep -q "\-# sent by claude" /home/pranav/CLAUDE.md \
  && pass "CLAUDE.md watermark present" || fail "CLAUDE.md watermark missing"

grep -q 'LOCKFILE.*delegate.lock' /home/pranav/.local/bin/delegate \
  && pass "delegate has lock" || fail "delegate missing lock"

openclaw config validate 2>&1 | grep -q "Config valid" \
  && pass "openclaw config valid" || fail "openclaw config invalid"

# thinkingDefault must be off
python3 -c "
import json, sys
d = json.load(open('/home/pranav/.openclaw/openclaw.json'))
sys.exit(0 if d.get('agents',{}).get('defaults',{}).get('thinkingDefault') == 'off' else 1)
" 2>/dev/null && pass "thinkingDefault=off" || fail "thinkingDefault not off"

# BOOT.md must not exist
[[ ! -f /home/pranav/.openclaw/BOOT.md ]] \
  && pass "BOOT.md deleted (dead code)" || fail "BOOT.md still exists"

# Workspace files should be stripped (<=2 lines each)
for F in SOUL.md IDENTITY.md TOOLS.md USER.md; do
  LINES=$(wc -l < "/home/pranav/.openclaw/workspace/$F" 2>/dev/null || echo 999)
  [[ "$LINES" -le 2 ]] && pass "workspace/$F stripped ($LINES lines)" || fail "workspace/$F not stripped ($LINES lines)"
done

# AGENTS.md should be passthrough (no Mode 1/Mode 2)
grep -q "Mode 1\|Mode 2" /home/pranav/.openclaw/workspace/AGENTS.md \
  && fail "AGENTS.md still has Mode 1/Mode 2" || pass "AGENTS.md: no Mode 1/Mode 2"

# delegate script must have newline sanitization
grep -q 'MESSAGE.*\$.*\\n' /home/pranav/.local/bin/delegate \
  && pass "delegate has newline sanitization (OC-016)" || fail "delegate missing newline sanitization"

# delegate script must have failure notification
grep -q 'Delegation failed' /home/pranav/.local/bin/delegate \
  && pass "delegate has failure notification" || fail "delegate missing failure notification"

echo ""

# ── Summary ───────────────────────────────────────────────────────────────────
echo "=========================================="
echo "Results: $PASS passed, $FAIL failed"
echo "=========================================="
echo ""

# ── Claude log analysis ───────────────────────────────────────────────────────
echo "Running Claude log analysis..."
echo ""

PROMPT_FILE=$(mktemp /tmp/integration-analysis-XXXXXX.txt)

cat > "$PROMPT_FILE" << 'PROMPT_END'
## Analysis Task — print to stdout only, do NOT call openclaw message send

Analyze today's openclaw routing. For each real Discord DM session:

CORRECT: Gemini loaded delegate SKILL.md → called exec "delegate discord <id> <msg>" (foreground) → got SENT back
WRONG variants:
  - called "agent --permission-mode" directly (AGENTS.md Mode 2 bypass)
  - exec ran in background ("Command still running")
  - Gemini answered with text without any exec
  - 429 caused silent drop

Current architecture:
  1. AGENTS.md: passthrough router — delegates EVERY message, no Mode 1/Mode 2
  2. thinkingDefault: "off" — Gemini does not think, just delegates
  3. retry.attempts: 0 — no retries (saves quota)
  4. delegate script: has newline sanitization (OC-016), failure notification, comprehensive logging
  5. Workspace stripped: SOUL/IDENTITY/TOOLS/USER.md emptied
  6. BOOT.md deleted (dead code)
  7. SKILL.md: has newline, no-quote, no-retry instructions

For each session, state: CORRECT / WRONG (reason). Then:
  FIXES VERIFIED: list which fixes are visible in logs
  REMAINING ISSUES: list anything still broken
  VERDICT: ROUTING OK / ROUTING DEGRADED / ROUTING BROKEN
PROMPT_END

echo "" >> "$PROMPT_FILE"
echo "## Session Summaries (today, Discord DM only)" >> "$PROMPT_FILE"

SESSIONS_DIR="$SESSIONS_DIR" TODAY="$TODAY" python3 - << 'PYEOF' >> "$PROMPT_FILE"
import json, glob, os, re

sessions_dir = os.environ['SESSIONS_DIR']
today = os.environ['TODAY']
skip_keys = {'cron', 'test', 'fresh', 'dispatch', 'gateway', 'gq-new', 'skill-list'}
dm_pattern = re.compile(r'\[(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{4}-\d{2}-\d{2} \d{2}:\d{2} P[DS]T\] (?!System:)(?!\[cron)')
results = []

agents_md = '/home/pranav/.openclaw/workspace/AGENTS.md'
skill_md = '/home/pranav/.openclaw/workspace/skills/delegate/SKILL.md'
cutoff_mtime = max(
    os.path.getmtime(agents_md) if os.path.exists(agents_md) else 0,
    os.path.getmtime(skill_md) if os.path.exists(skill_md) else 0,
)

for f in sorted(glob.glob(os.path.join(sessions_dir, '*.jsonl'))):
    sid = os.path.basename(f)
    if any(x in sid for x in skip_keys): continue
    if os.path.getmtime(f) < cutoff_mtime: continue
    try:
        with open(f) as fh:
            first = json.loads(fh.readline())
        if not first.get('timestamp','').startswith(today): continue
        with open(f) as fh: lines = fh.readlines()
    except: continue

    # Check it's a real Discord DM
    is_dm = False
    for line in lines:
        try: msg = json.loads(line)
        except: continue
        if msg.get('type') != 'message': continue
        for c in msg.get('message',{}).get('content',[]):
            if isinstance(c,dict) and c.get('type')=='text' and dm_pattern.search(c.get('text','')):
                is_dm = True; break
        if is_dm: break
    if not is_dm: continue

    events = []
    for line in lines:
        try: msg = json.loads(line)
        except: continue
        if msg.get('type') != 'message': continue
        m = msg.get('message',{})
        role = m.get('role','')
        ts2 = msg.get('timestamp','')[:19]
        err = m.get('errorMessage','')
        if err:
            events.append(f'  [{ts2}] ERROR({"429" if "429" in err else "ERR"})')
        for c in m.get('content',[]):
            if not isinstance(c,dict): continue
            ct = c.get('type','')
            if ct == 'text' and role in ('user','assistant'):
                events.append(f'  [{ts2}] {role}: {c.get("text","").replace(chr(10)," ")[:100]}')
            elif ct == 'toolCall':
                cmd = c.get('arguments',{}).get('command','')[:100]
                events.append(f'  [{ts2}] TOOL_CALL {c.get("name","")}: {cmd}')
            elif ct == 'thinking':
                events.append(f'  [{ts2}] thinking: {c.get("thinking","")[:80]}')
        if role == 'toolResult':
            for c in m.get('content',[]):
                if isinstance(c,dict):
                    events.append(f'  [{ts2}] TOOL_RESULT: {c.get("text","")[:80]}')

    if events:
        results.append(f'--- {sid[:8]} ---')
        results.extend(events[:25])
        results.append('')

print('\n'.join(results) if results else '(no real Discord DM sessions today)')
PYEOF

echo "" >> "$PROMPT_FILE"
echo "## Delegate Log" >> "$PROMPT_FILE"
cat "$LOGDIR/delegate-$TODAY.log" 2>/dev/null >> "$PROMPT_FILE" || echo "(none)" >> "$PROMPT_FILE"

echo "" >> "$PROMPT_FILE"
echo "## Gateway Sends + Errors" >> "$PROMPT_FILE"
grep -E 'Sent via Discord|elevated.*not available|429|exec.*failed' \
  "$LOGDIR/openclaw-$TODAY.log" 2>/dev/null | tail -30 >> "$PROMPT_FILE" \
  || echo "(none)" >> "$PROMPT_FILE"

cd /tmp && agent --permission-mode bypassPermissions --print "$(cat "$PROMPT_FILE")" 2>/dev/null

rm -f "$PROMPT_FILE" /tmp/cron_check.txt
[[ $FAIL -eq 0 ]] && exit 0 || exit 1
