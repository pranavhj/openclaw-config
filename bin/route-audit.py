#!/usr/bin/env python3
"""route-audit.py — daily routing audit for the openclaw pipeline.

Reads delegate/timeline logs and the discord-bot NSSM log, runs analysis
via Claude, and sends a summary to Discord.

Usage: python route-audit.py [YYYY-MM-DD]   # defaults to yesterday
"""
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
AGENT_SMART_PY = SCRIPT_DIR / 'agent-smart.py'

LOGDIR = Path(os.getenv('LOCALAPPDATA') or tempfile.gettempdir()) / 'openclaw'
WORK_DIR = Path.home() / 'projects' / 'openclaw'
DISCORD_TARGET = '1482473282925101217'
BOT_LOG = LOGDIR / 'bot.log'

ALLOWED_SCRIPTS = {
    'delegate.py', 'route-audit.py', 'run-tests.py', 'discord-bot.py',
    'discord-send.py', 'bot-logs.py', 'session-reset.py', 'agent-smart.py',
    'openclaw-timeline', 'openclaw-timeline.py',
}


def main():
    if len(sys.argv) > 1:
        date = sys.argv[1]
    else:
        date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d')

    # Gather delegate log
    delegate_log_path = LOGDIR / f'delegate-{date}.log'
    if delegate_log_path.exists():
        delegate_log = delegate_log_path.read_text(encoding='utf-8', errors='replace')
    else:
        delegate_log = f'(no delegate log for {date})'

    # Gather timeline log
    timeline_log_path = LOGDIR / f'timeline-{date}.log'
    if timeline_log_path.exists():
        timeline_log = timeline_log_path.read_text(encoding='utf-8', errors='replace')
    else:
        timeline_log = f'(no timeline log for {date})'

    # Discord bot service health via NSSM / sc
    bot_status = _run_cmd(['sc', 'query', 'discord-bot'])
    bot_dispatches = _count_in_log(BOT_LOG, date, 'dispatch channel')
    bot_restarts = _count_in_log(BOT_LOG, date, 'ready user=')

    # Binary integrity check
    rogue = []
    if SCRIPT_DIR.exists():
        for f in SCRIPT_DIR.iterdir():
            if not f.name.startswith('.') and f.name not in ALLOWED_SCRIPTS:
                rogue.append(f.name)
    bin_integrity = f'Allowed: {", ".join(sorted(ALLOWED_SCRIPTS))}'
    if rogue:
        bin_integrity += f' | ROGUE: {", ".join(sorted(rogue))}'

    prompt = f"""## Task: Daily Routing Audit

You are auditing the openclaw system for {date}. Analyze the logs and send a concise summary to Discord.

**Pipeline (Windows native):**
Discord DM -> discord-bot.py (NSSM service) -> subprocess delegate.py -> claude --model sonnet --continue -> discord-send.py -> Discord

**What to check:**
1. Delegation success rate: delegate_recv events vs agent_done with exit_code=0
2. Failure patterns: failure_detected events, non-zero exit codes, "hit your limit" (Claude usage cap)
3. Timing: flag any agent_done duration_ms > 60000 (slow) or < 3000 (suspiciously fast)
4. Lock contention: lock_blocked events (user sent message while previous was running)
5. Discord bot health: restarts during the day, dispatch count matches delegate_recv count
6. Rogue binaries: anything unexpected in the bin directory

**Red flags:**
- agent_done exit_code != 0 -- delegation failed
- output_preview contains "hit your limit" -- Claude Code usage cap hit, no response to user
- duration_ms < 3000 with exit_code != 0 -- fast failure, likely auth/quota error
- BOT_RESTARTS > 2 -- service instability
- lock_blocked with no follow-up from user -- dropped message

**Send your summary using:**
python {SCRIPT_DIR / 'discord-send.py'} --target {DISCORD_TARGET} --message "<summary>"

Keep it brief -- bullet points, key numbers, any action items.

## Date: {date}

## Discord Bot Health
Service restarts on {date}: {bot_restarts}
Dispatch events in log: {bot_dispatches}

{bot_status}

## Binary Integrity
{bin_integrity}

## Delegate Log (human-readable)
{delegate_log}

## Timeline Log (JSON-lines)
{timeline_log}"""

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(AGENT_SMART_PY),
         '--continue', '--permission-mode', 'bypassPermissions',
         '--model', 'sonnet', '--print', prompt],
        cwd=str(WORK_DIR),
    )
    sys.exit(result.returncode)


def _run_cmd(cmd: list) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return (result.stdout or result.stderr or '(no output)').strip()
    except Exception as e:
        return f'(error: {e})'


def _count_in_log(log_path: Path, date: str, keyword: str) -> int:
    if not log_path.exists():
        return 0
    try:
        return sum(
            1 for line in log_path.read_text(encoding='utf-8', errors='replace').splitlines()
            if date in line and keyword in line
        )
    except Exception:
        return 0


if __name__ == '__main__':
    main()
