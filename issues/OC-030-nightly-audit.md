# OC-030 — Nightly Audit: Rule-Based Log Health Checks + Daily Discord Report

**Type:** feature
**Status:** done
**Severity:** medium

## Goal

Run a nightly job at 3:30 AM that audits yesterday's interaction logs and sends a
health report to Discord DM. Free to run (rule-based, no tokens). Optionally extend
later with Haiku quality scoring.

## Log sources

| File | Events |
|------|--------|
| `timeline-router-YYYY-MM-DD.log` | `delegate_recv` → `lock_acquired` → `project_match` → `prompt_ready` → `agent_start` → `agent_done` → `delegate_reply` → `delegate_exit` |
| `discord-timeline-YYYY-MM-DD.log` | `message_received` → `delegate_spawn` → `delegate_spawned` → `session_watcher_*` |
| `gateway-timeline-YYYY-MM-DD.log` | `request_received` → `ask_received` → `agent_done` → `ask_success` → `request_done` |

All logs live in `%LOCALAPPDATA%\openclaw\` (Windows: `C:\Users\prana\AppData\Local\openclaw\`).

## Rule-based checks (Phase 1 — no tokens)

| Rule | Severity | Condition |
|------|----------|-----------|
| `exit_nonzero` | high | `exit_code != 0` |
| `no_reply` | high | No `delegate_reply` event after `agent_done` and output lacks "SENT" |
| `near_timeout` | high | `total_ms >= 110000` |
| `slow` | medium | `total_ms >= 60000` |
| `failure_detected` | high | Explicit `failure_detected` event present |
| `stdout_forward` | medium | `stdout_forward` event — Claude printed stdout instead of discord-send |
| `stale_lock` | medium | `stale_lock_broken` event — previous run crashed without cleanup |
| `lock_blocked` | high | `lock_blocked` event — concurrent request was dropped |
| `tiny_prompt` | low | `prompt_bytes < 800` — context may be missing |

## Planned phases

- **Phase 1 (built):** Rule-based checks + daily Discord report (no tokens)
- **Phase 2 (built):** LLM Gateway quality scoring for high-severity flagged sessions
- **Phase 3 (built):** LLM Gateway optimization suggestions when failures/slowness detected
- **Phase 4 (built):** Safe auto-fix cycle — gateway generates patches, applied with full test-before/after + commit+push

## Implementation

- **Script:** `D:\MyData\Software\openclaw-config\bin\nightly-audit.py`
- **Scheduling:** Windows Task Scheduler — `NightlyAudit` task, daily at 03:30
- **Report target:** Discord DM `1482473282925101217`

## Scheduling command

```
schtasks /create /tn "NightlyAudit" /tr "python D:\MyData\Software\openclaw-config\bin\nightly-audit.py" /sc DAILY /st 03:30 /f
```

## Safe change cycle (Phase 4)

Each auto-fix goes through:
1. Run baseline tests — abort if already failing
2. Apply change
3. Run tests — revert if broken
4. Write new tests validating the change
5. Run tests — revert both if new tests fail
6. `git commit -m "fix(audit): <desc>"` + `git push`

**Architecture caution**: `PROTECTED_FILES` = `{llm-gateway.py, gateway-delegate.py, project_store.py, discord-bot.py, discord-send.py}`. For these, `safe_change_cycle` re-reads the file, verifies the old snippet exists, and rejects changes with delta >200 chars.

## Files Changed

- `bin/nightly-audit.py` (new + phases 2/3 added; phase 4 + safe-change scaffolding added)
- `tests/test_nightly_audit.py` (sections 13-16 added: run_tests, check_file_safety, safe_change_cycle, phase4_autofix)
- `ISSUES.md` (added OC-030)
- `CLAUDE.md` (added nightly audit section)
- `~/projects/nightly_audit_llm_gateway/` (new gateway project for AI analysis)
- Windows Task Scheduler: `NightlyAudit` task
