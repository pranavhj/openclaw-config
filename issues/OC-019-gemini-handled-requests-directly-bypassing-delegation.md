# OC-019 — Gemini handled requests directly, bypassing delegation

**Type:** bug
**Status:** fixed
**Severity:** high

## Symptom

2026-03-30 18:40–18:45 PDT: After the "Yes please do it" delegate exec completed, the next user
message arrived packaged with the exec-completed system notification. Gemini handled that turn
and subsequent turns directly instead of delegating:
- Used `write` tool to create `.github/workflows/build.yml`
- Used `exec` to run `git commit && git push` directly (not via delegate)
- Replied with `[[reply_to_current]]` text 3 times — no Claude watermark, no Discord formatting

User saw raw Gemini replies instead of Claude responses.

## Root Cause

When the gateway bundles an exec-completed notification + a new user message into a single turn,
Gemini interprets the new message as requiring a direct response rather than delegation. The
existing "STOP after exec" rule applies to the exec result, but Gemini treats the new user
message in the same turn as a fresh prompt and starts doing work itself.

Secondary: Gemini had no explicit prohibition on using `write`, `read`, or other non-exec tools.

## Fix

Added two lines to AGENTS.md:
1. Explicit rule: "If a new user message arrives in the same turn as exec completion → delegate it with exec again."
2. Explicit prohibition: "NEVER use write, read, bash, or any tool other than exec and the allowed skill exceptions."

Kept AGENTS.md minimal to avoid token bloat confusing Gemini.

## Files Changed

- `/home/pranav/.openclaw/workspace/AGENTS.md`
- `/home/pranav/openclaw-config/ISSUES.md`
- `/home/pranav/test_integration.sh` (added `session_used_non_exec_tool` coverage)
- `/home/pranav/test_delegate.sh` (Test 27 AGENTS.md sanity already covers size)
