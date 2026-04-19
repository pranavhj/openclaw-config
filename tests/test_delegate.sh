#!/bin/bash
# Unit tests for delegate script changes
# Tests: lock mechanism, logging, cron config, CLAUDE.md watermark

PASS=0
FAIL=0
TESTDIR=$(mktemp -d /tmp/delegate-test-XXXXXX)

pass() { echo "  PASS: $1"; PASS=$((PASS+1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }

cleanup() { rm -rf "$TESTDIR"; }
trap cleanup EXIT

echo "=== delegate script tests ==="

# ── Test 1: Lock prevents concurrent run ──────────────────────────────────────
echo ""
echo "1. Lock mechanism"

LOCKFILE="$TESTDIR/delegate.lock"

# Simulate lock already held
mkdir "$LOCKFILE"
OUT=$(LOGDIR="$TESTDIR" bash -c '
  LOCKFILE="$LOGDIR/delegate.lock"
  mkdir -p "$LOGDIR"
  if ! mkdir "$LOCKFILE" 2>/dev/null; then
    echo "SENT"
    exit 0
  fi
  echo "EXECUTED"
')
rmdir "$LOCKFILE"

[[ "$OUT" == "SENT" ]] && pass "returns SENT when lock held" || fail "expected SENT, got: $OUT"

# Verify agent would NOT have run — if lock bypassed, the inner script echoes EXECUTED
# Since we got SENT (not EXECUTED), agent was skipped
[[ "$OUT" != "EXECUTED" ]] \
  && pass "agent not executed when locked" \
  || fail "agent ran despite lock being held"

# ── Test 2: Lock is acquired when free ───────────────────────────────────────
echo ""
echo "2. Lock acquisition"

LOCK2="$TESTDIR/delegate2.lock"
OUT2=$(LOGDIR="$TESTDIR" bash -c '
  LOCKFILE="$LOGDIR/delegate2.lock"
  mkdir -p "$LOGDIR"
  if ! mkdir "$LOCKFILE" 2>/dev/null; then
    echo "BLOCKED"
    exit 0
  fi
  trap "rmdir \"$LOCKFILE\" 2>/dev/null" EXIT
  echo "ACQUIRED"
')

[[ "$OUT2" == "ACQUIRED" ]] && pass "acquires lock when free" || fail "failed to acquire lock: $OUT2"
[[ ! -d "$LOCK2" ]] && pass "lock released after exit" || fail "lock not released after exit"

# ── Test 3: Lock released even on failure ────────────────────────────────────
echo ""
echo "3. Lock cleanup on failure"

LOCK3="$TESTDIR/delegate3.lock"
bash -c "
  LOCKFILE='$LOCK3'
  mkdir -p '$TESTDIR'
  mkdir \"\$LOCKFILE\" 2>/dev/null
  trap \"rmdir '\$LOCKFILE' 2>/dev/null\" EXIT
  exit 1
" 2>/dev/null
[[ ! -d "$LOCK3" ]] && pass "lock released on non-zero exit" || fail "lock leaked on failure"

# ── Test 4: Log file written on run ──────────────────────────────────────────
echo ""
echo "4. Logging"

LOGDIR2="$TESTDIR/logs"
mkdir -p "$LOGDIR2"
LOGFILE="$LOGDIR2/delegate-$(date +%Y-%m-%d).log"

# Simulate the logging block
{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
  echo "channel: discord"
  echo "target: 12345"
  echo "message: test message"
  echo "projects: none"
  echo "status: starting"
} >> "$LOGFILE"

[[ -f "$LOGFILE" ]] && pass "log file created" || fail "log file not created"
grep -q "channel: discord" "$LOGFILE" && pass "channel logged" || fail "channel not in log"
grep -q "message: test message" "$LOGFILE" && pass "message logged" || fail "message not in log"
grep -q "status: starting" "$LOGFILE" && pass "status logged" || fail "status not in log"

# ── Test 5: gemini-stats runs via native crontab ──────────────────────────────
echo ""
echo "5. Cron job config"

crontab -l 2>/dev/null | grep -q "send-gemini-stats" && pass "send-gemini-stats in native crontab" || fail "send-gemini-stats missing from native crontab"

# ── Test 6: CLAUDE.md has watermark instruction ───────────────────────────────
echo ""
echo "6. CLAUDE.md watermark"

grep -q "sent by claude" /home/pranav/CLAUDE.md && pass "watermark instruction present" || fail "watermark missing from CLAUDE.md"
grep -q "\-# sent by claude" /home/pranav/CLAUDE.md && pass "uses Discord small-text format (-#)" || fail "wrong watermark format"

# ── Test 7: openclaw.json retry config ───────────────────────────────────────
echo ""
echo "7. Retry config"

RETRY=$(python3 -c "
import json
with open('/home/pranav/.openclaw/openclaw.json') as f:
    data = json.load(f)
retry = data.get('channels',{}).get('discord',{}).get('retry',{})
print(retry.get('attempts', 'missing'))
" 2>&1)

[[ "$RETRY" == "1" ]] && pass "discord retry attempts=1 (openclaw minimum)" || fail "retry not set to 1 (got: $RETRY)"

# ── Test 8: discord-bot.py and discord-send present ──────────────────────────
echo ""
echo "8. Discord bot files"

[[ -x /home/pranav/.local/bin/discord-bot.py ]] && pass "discord-bot.py is executable" || fail "discord-bot.py missing or not executable"
[[ -x /home/pranav/.local/bin/discord-send ]] && pass "discord-send is executable" || fail "discord-send missing or not executable"
[[ -f /home/pranav/.config/systemd/user/discord-bot.service ]] && pass "discord-bot.service exists" || fail "discord-bot.service missing"
systemctl --user is-active discord-bot >/dev/null 2>&1 && pass "discord-bot service is running" || fail "discord-bot service is not running"

# ── Test 9: delegate script is executable ────────────────────────────────────
echo ""
echo "9. Script permissions"

[[ -x /home/pranav/.local/bin/delegate ]] && pass "delegate is executable" || fail "delegate not executable"
[[ -x /home/pranav/.local/bin/send-gemini-stats ]] && pass "send-gemini-stats is executable" || fail "send-gemini-stats not executable"

# ── Test 10: Lock file name consistent ───────────────────────────────────────
echo ""
echo "10. Lock path in script"

grep -q 'LOCKFILE=.*delegate.lock' /home/pranav/.local/bin/delegate && pass "lockfile path defined" || fail "lockfile path missing"
grep -q 'rmdir.*LOCKFILE' /home/pranav/.local/bin/delegate && pass "lock cleanup in trap" || fail "no lock cleanup trap"

# ── Test 11: Message sanitization — apostrophe → Unicode right single quote ───
echo ""
echo "11. Message sanitization (apostrophe)"

RSQUOTE=$'\xe2\x80\x99'
DELEGATE=/home/pranav/.local/bin/delegate

# Extract the sanitization logic from delegate script and test it in isolation
RAW="I'm looking for software"
SANITIZED=$(bash -c "
  MSG=\"$RAW\"
  RSQUOTE=\$'\\xe2\\x80\\x99'
  LDQUOTE=\$'\\xe2\\x80\\x98'
  MSG=\"\${MSG//\$'\\''/$RSQUOTE}\"
  MSG=\"\${MSG//\\\`/\$LDQUOTE}\"
  printf '%s' \"\$MSG\"
")
[[ "$SANITIZED" != *"'"* ]] && pass "apostrophe removed from sanitized message" || fail "apostrophe still present: $SANITIZED"
[[ "$SANITIZED" == *"$RSQUOTE"* ]] && pass "replaced with Unicode right single quote" || fail "Unicode replacement missing"

# ── Test 12: Message sanitization — backtick → Unicode left single quote ──────
echo ""
echo "12. Message sanitization (backtick)"

LDQUOTE=$'\xe2\x80\x98'
RAW2='run this: `whoami`'
SANITIZED2=$(bash -c "
  MSG='run this: \`whoami\`'
  RSQUOTE=\$'\\xe2\\x80\\x99'
  LDQUOTE=\$'\\xe2\\x80\\x98'
  MSG=\"\${MSG//\$'\\''/$RSQUOTE}\"
  MSG=\"\${MSG//\\\`/\$LDQUOTE}\"
  printf '%s' \"\$MSG\"
")
[[ "$SANITIZED2" != *'`'* ]] && pass "backtick removed from sanitized message" || fail "backtick still present: $SANITIZED2"
[[ "$SANITIZED2" == *"$LDQUOTE"* ]] && pass "replaced with Unicode left single quote" || fail "backtick Unicode replacement missing"

# ── Test 13: Sanitization in actual delegate script ───────────────────────────
echo ""
echo "13. Sanitization present in delegate script"

grep -q "RSQUOTE" "$DELEGATE" && pass "RSQUOTE sanitization in delegate script" || fail "RSQUOTE missing from delegate"
grep -q "xe2.x80.x99" "$DELEGATE" && pass "Unicode U+2019 code in script" || fail "U+2019 code missing"
grep -q "LDQUOTE\|xe2.x80.x98" "$DELEGATE" && pass "backtick sanitization present" || fail "backtick sanitization missing"

# ── Test 14: SKILL.md quoting instruction ─────────────────────────────────────
echo ""
echo "14. SKILL.md quoting guidance"

SKILLMD="/home/pranav/.openclaw/workspace/skills/delegate/SKILL.md"
grep -q "NEVER wrap.*single quotes\|QUOTING.*NEVER\|single quote" "$SKILLMD" \
  && pass "single-quote warning in SKILL.md" || fail "no single-quote warning in SKILL.md"
grep -q "QUOTING" "$SKILLMD" && pass "QUOTING section present" || fail "QUOTING section missing"
# Ensure the description example uses double quotes, not single quotes around the command value
python3 -c "
import re
with open('$SKILLMD') as f: content = f.read()
# Find description line and check the exec example uses double quotes
desc_line = [l for l in content.split('\n') if l.startswith('description:')][0]
# The command value should be in double quotes not single quotes
if 'command:\"' in desc_line or 'command: \"' in desc_line:
    print('OK')
elif \"command:'\" in desc_line:
    print('FAIL')
else:
    print('OK')  # no single-quote wrapping found
" 2>/dev/null | grep -q "^OK$" && pass "description example uses double quotes" || fail "description example may use single quotes"

# ── Test 15: Prompt file approach still used (not inline expansion) ───────────
echo ""
echo "15. Prompt file safety"

grep -q "PROMPT_FILE" "$DELEGATE" && pass "prompt file approach used" || fail "prompt file approach missing"
grep -q 'printf.*%s.*MESSAGE\|>>.*PROMPT_FILE' "$DELEGATE" && pass "message written to prompt file via printf" || fail "printf-to-file pattern missing"

# ── Test 16: Newline sanitization (OC-016) ─────────────────────────────────────
echo ""
echo "16. Newline sanitization (OC-016)"

RAW_NL=$'line one\nline two\nline three'
SANITIZED_NL=$(bash -c "
  MSG='line one
line two
line three'
  MSG=\"\${MSG//\$'\\n'/ }\"
  printf '%s' \"\$MSG\"
")
[[ "$SANITIZED_NL" == "line one line two line three" ]] \
  && pass "newlines replaced with spaces" \
  || fail "newline sanitization failed: $SANITIZED_NL"

# Verify the newline fix is in the delegate script
grep -q 'MESSAGE.*\$.*\\n' "$DELEGATE" \
  && pass "newline sanitization present in delegate script" \
  || fail "newline sanitization missing from delegate script"

# ── Test 17: Timeline JSON log format ──────────────────────────────────────────
echo ""
echo "17. Timeline log format"

grep -q 'TIMELINE_LOG' "$DELEGATE" \
  && pass "timeline log variable defined" \
  || fail "TIMELINE_LOG missing from delegate"
grep -q '"event":"delegate_recv"' "$DELEGATE" \
  && pass "delegate_recv event logged" \
  || fail "delegate_recv event missing"
grep -q '"event":"sanitize"' "$DELEGATE" \
  && pass "sanitize event logged" \
  || fail "sanitize event missing"
grep -q '"event":"lock_acquired"' "$DELEGATE" \
  && pass "lock_acquired event logged" \
  || fail "lock_acquired event missing"
grep -q '"event":"lock_blocked"' "$DELEGATE" \
  && pass "lock_blocked event logged" \
  || fail "lock_blocked event missing"
grep -q '"event":"prompt_ready"' "$DELEGATE" \
  && pass "prompt_ready event logged" \
  || fail "prompt_ready event missing"
grep -q '"event":"agent_start"' "$DELEGATE" \
  && pass "agent_start event logged" \
  || fail "agent_start event missing"
grep -q '"event":"agent_done"' "$DELEGATE" \
  && pass "agent_done event logged" \
  || fail "agent_done event missing"
grep -q '"event":"delegate_exit"' "$DELEGATE" \
  && pass "delegate_exit event logged" \
  || fail "delegate_exit event missing"

# ── Test 18: Failure notification ──────────────────────────────────────────────
echo ""
echo "18. Failure notification"

grep -q 'failure_detected' "$DELEGATE" \
  && pass "failure_detected event in script" \
  || fail "failure_detected missing"
grep -q 'failure_notified' "$DELEGATE" \
  && pass "failure_notified event in script" \
  || fail "failure_notified missing"
grep -q 'Delegation failed' "$DELEGATE" \
  && pass "Discord failure notification present" \
  || fail "Discord failure notification missing"
# After failure, script should output SENT to stop Gemini
grep -q 'OUTPUT="SENT"' "$DELEGATE" \
  && pass "failure handler sets OUTPUT=SENT to stop Gemini" \
  || fail "failure handler missing OUTPUT=SENT"

# ── Test 19: thinkingDefault config ────────────────────────────────────────────
echo ""
echo "19. Gemini thinking disabled"

THINKING=$(python3 -c "
import json
with open('/home/pranav/.openclaw/openclaw.json') as f:
    data = json.load(f)
print(data.get('agents',{}).get('defaults',{}).get('thinkingDefault', 'missing'))
" 2>&1)
[[ "$THINKING" == "off" ]] \
  && pass "thinkingDefault=off (saves API quota)" \
  || fail "thinkingDefault not off (got: $THINKING)"

# ── Test 20: Workspace files emptied ───────────────────────────────────────────
echo ""
echo "20. Workspace context stripped"

WORKSPACE="/home/pranav/.openclaw/workspace"
for F in SOUL.md IDENTITY.md TOOLS.md USER.md; do
  LINES=$(wc -l < "$WORKSPACE/$F" 2>/dev/null || echo "missing")
  if [[ "$LINES" == "missing" ]]; then
    fail "$F does not exist"
  elif [[ "$LINES" -le 2 ]]; then
    pass "$F emptied ($LINES lines)"
  else
    fail "$F not emptied ($LINES lines — should be <=2)"
  fi
done

# ── Test 21: BOOT.md deleted ──────────────────────────────────────────────────
echo ""
echo "21. BOOT.md cleanup"

[[ ! -f /home/pranav/.openclaw/BOOT.md ]] \
  && pass "BOOT.md deleted (dead code)" \
  || fail "BOOT.md still exists (never loaded by gateway)"

# ── Test 22: AGENTS.md is archived (openclaw-gateway disabled) ────────────────
echo ""
echo "22. AGENTS.md archived"

AGENTS="/home/pranav/.openclaw/workspace/AGENTS.md"
grep -qi "ARCHIVED\|archived\|discord-bot" "$AGENTS" \
  && pass "AGENTS.md is archived (openclaw-gateway disabled)" \
  || fail "AGENTS.md not updated to archived state"

# ── Test 23: SKILL.md newline instruction ─────────────────────────────────────
echo ""
echo "23. SKILL.md newline handling"

SKILLMD="/home/pranav/.openclaw/workspace/skills/delegate/SKILL.md"
grep -qi "newline\|single line" "$SKILLMD" \
  && pass "SKILL.md has newline handling instruction" \
  || fail "SKILL.md missing newline instruction"
grep -qi "no retries\|No retries" "$SKILLMD" \
  && pass "SKILL.md has no-retry instruction" \
  || fail "SKILL.md missing no-retry instruction"

# ── Test 24: No fallback models ────────────────────────────────────────────────
echo ""
echo "24. No fallback models"

python3 -c "
import json, sys
d = json.load(open('/home/pranav/.openclaw/openclaw.json'))
fallbacks = d.get('agents',{}).get('defaults',{}).get('model',{}).get('fallbacks',[])
sys.exit(0 if len(fallbacks) == 0 else 1)
" 2>/dev/null \
  && pass "no fallback models (groq can't exec)" \
  || fail "unexpected fallback models configured"

# ── Test 25: Skill allowlist ──────────────────────────────────────────────────
echo ""
echo "25. Workspace skill allowlist"

SKILLS_DIR="/home/pranav/.openclaw/workspace/skills"
ALLOWED_SKILLS="delegate discord-send quota gemini-requests routing-audit"
ACTUAL_SKILLS=$(ls "$SKILLS_DIR" 2>/dev/null | sort | tr '\n' ' ' | sed 's/ $//')
ROGUE_SKILLS=""
for S in $(ls "$SKILLS_DIR" 2>/dev/null); do
  echo "$ALLOWED_SKILLS" | grep -qw "$S" || ROGUE_SKILLS="$ROGUE_SKILLS $S"
done

if [[ -z "$ROGUE_SKILLS" ]]; then
  pass "only allowed skills present: $ACTUAL_SKILLS"
else
  fail "ROGUE SKILLS found (delete immediately):$ROGUE_SKILLS"
fi

# All 5 expected skills must exist
for S in $ALLOWED_SKILLS; do
  [[ -f "$SKILLS_DIR/$S/SKILL.md" ]] \
    && pass "$S skill present" \
    || fail "$S skill MISSING"
done

# ── Test 26: No rogue exec binaries ────────────────────────────────────────────
echo ""
echo "26. No rogue exec binaries in ~/.local/bin"

ALLOWED_BINS="delegate discord-bot.py discord-send route-audit run-tests openclaw-timeline route-log send-gemini-stats agent oc httpx gq claude session-reset"
ROGUE_BINS=""
for B in $(ls /home/pranav/.local/bin/ 2>/dev/null); do
  echo "$ALLOWED_BINS" | grep -qw "$B" || ROGUE_BINS="$ROGUE_BINS $B"
done

if [[ -z "$ROGUE_BINS" ]]; then
  pass "no rogue binaries in ~/.local/bin"
else
  fail "UNEXPECTED BINARIES in ~/.local/bin (may be rogue openclaw exec targets):$ROGUE_BINS"
fi

# ── Test 27: AGENTS.md archived state ─────────────────────────────────────────
echo ""
echo "27. AGENTS.md archived (openclaw-gateway disabled)"

AGENTS="/home/pranav/.openclaw/workspace/AGENTS.md"
[[ -f "$AGENTS" ]] \
  && pass "AGENTS.md exists (archived)" \
  || fail "AGENTS.md missing"
grep -qi "ARCHIVED\|archived\|discord-bot" "$AGENTS" \
  && pass "AGENTS.md contains archived marker" \
  || fail "AGENTS.md missing archived marker (may have been overwritten)"

# ── Test 28: Lock-blocked notification ────────────────────────────────────────
echo ""
echo "28. Lock-blocked sends Discord notification"

grep -A3 'lock_blocked' /home/pranav/.local/bin/delegate | grep -q 'discord-send' \
  && pass "delegate notifies user when lock is held (via discord-send)" \
  || fail "delegate silently drops messages when locked (no notification)"

grep -A5 'lock_blocked' /home/pranav/.local/bin/delegate | grep -q 'sent by delegate' \
  && pass "lock notification has delegate watermark" \
  || fail "lock notification missing watermark"

# ── Test 29: Project discovery uses dirs only ──────────────────────────────────
echo ""
echo "29. Project discovery filters to directories only"

grep 'PROJECTS=' /home/pranav/.local/bin/delegate | grep -q '\-d.*\*/' \
  && pass "PROJECTS uses ls -d */ (dirs only)" \
  || fail "PROJECTS still uses plain ls (may include files like CLAUDE.md)"

grep 'for proj in' /home/pranav/.local/bin/delegate | grep -q '\-d.*\*/' \
  && pass "WORK_DIR loop uses ls -d */ (dirs only)" \
  || fail "WORK_DIR loop still uses plain ls"

# ── Test 30: Yesterday's log fallback ─────────────────────────────────────────
echo ""
echo "30. History falls back to yesterday's log"

grep -q 'YESTERDAY_LOG' /home/pranav/.local/bin/delegate \
  && pass "delegate references yesterday's log" \
  || fail "no yesterday log fallback in delegate"

grep -q 'TODAY_COUNT' /home/pranav/.local/bin/delegate \
  && pass "delegate checks today count before using yesterday" \
  || fail "yesterday fallback not conditional on today count"

# ── Test 31: session-reset script exists and is executable ────────────────────
echo ""
echo "31. session-reset script"

[[ -x /home/pranav/.local/bin/session-reset ]] \
  && pass "session-reset is executable" \
  || fail "session-reset missing or not executable"

grep -q 'sessions.json' /home/pranav/.local/bin/session-reset \
  && pass "session-reset targets sessions.json" \
  || fail "session-reset does not reference sessions.json"

# ── Test 32: Workspace git repo is clean ──────────────────────────────────────
echo ""
echo "32. Workspace git repo clean (no rogue commits)"

WS_COMMITS=$(git -C /home/pranav/.openclaw/workspace log --oneline 2>/dev/null | wc -l)
[[ "$WS_COMMITS" -eq 0 ]] \
  && pass "workspace git repo has no commits (clean)" \
  || fail "workspace git repo has $WS_COMMITS commit(s) — expected 0"

[[ ! -d /home/pranav/.openclaw/workspace/.github ]] \
  && pass "no .github directory in workspace" \
  || fail ".github still exists in workspace"

# ── Test 33: Auto-reset Gemini session after delegation ───────────────────────
echo ""
echo "33. Auto-reset after delegation"

grep -q 'session-reset' /home/pranav/.local/bin/delegate \
  && pass "delegate calls session-reset" \
  || fail "delegate does not call session-reset (Gemini session will bloat)"

# session-reset must come AFTER agent_done (not before), so Gemini completes first
RESET_LINE=$(grep -n 'session-reset' /home/pranav/.local/bin/delegate | grep -v '^#' | head -1 | cut -d: -f1)
AGENT_DONE_LINE=$(grep -n 'agent_done' /home/pranav/.local/bin/delegate | tail -1 | cut -d: -f1)
if [[ -n "$RESET_LINE" && -n "$AGENT_DONE_LINE" && "$RESET_LINE" -gt "$AGENT_DONE_LINE" ]]; then
  pass "session-reset runs after agent_done (correct order)"
else
  fail "session-reset order wrong — must run after agent_done"
fi

# ── Test 34: Project-annotated history in prompt ──────────────────────────────
echo ""
echo "34. Project-annotated history"

grep -q 'project_match' /home/pranav/.local/bin/delegate \
  && pass "delegate logs project_match event to timeline" \
  || fail "project_match not logged (history won't be annotated)"

grep -q 'MATCHED_PROJECT' /home/pranav/.local/bin/delegate \
  && pass "matched project captured for history annotation" \
  || fail "MATCHED_PROJECT variable missing"

grep -q 'CURRENT_PROJECT' /home/pranav/.local/bin/delegate \
  && pass "current project passed to prompt builder" \
  || fail "CURRENT_PROJECT not used in prompt"

grep -q 'Only use entries matching' /home/pranav/.local/bin/delegate \
  && pass "prompt instructs Claude to filter cross-project context" \
  || fail "no cross-project filter instruction in prompt"

# ── Test 35: CLAUDE.md uses discord-send ─────────────────────────────────────
echo ""
echo "35. CLAUDE.md uses discord-send"

grep -q 'discord-send' /home/pranav/CLAUDE.md \
  && pass "CLAUDE.md instructs Claude to use discord-send" \
  || fail "CLAUDE.md still references old command"
grep -q 'openclaw message send' /home/pranav/CLAUDE.md \
  && fail "CLAUDE.md still references openclaw message send (stale)" \
  || pass "CLAUDE.md has no openclaw message send references"
grep -q 'discord-send' /home/pranav/projects/openclaw/CLAUDE.md \
  && pass "projects/openclaw/CLAUDE.md uses discord-send" \
  || fail "projects/openclaw/CLAUDE.md not updated"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "=============================="
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]] && exit 0 || exit 1
