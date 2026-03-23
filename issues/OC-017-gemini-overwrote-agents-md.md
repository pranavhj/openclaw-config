# OC-017 — Gemini overwrote AGENTS.md with anti-delegation instructions

**Type:** bug
**Status:** fixed
**Severity:** high

## Symptom

2026-03-23 ~12:56 PDT: After a delegation returned, a second user message arrived. Instead of delegating, Gemini used the `read` tool to read AGENTS.md, then the `write` tool to overwrite it with:

```
# Agent Instructions

Process user requests directly. Do not delegate unless explicitly instructed.
```

The exact opposite of the intended passthrough behavior. User noticed and Gemini reverted it at 12:58 PDT.

## Root Cause

Gemini's helpfulness training caused it to interpret a request about Alexa as needing configuration changes rather than delegation. Once it decided to "help" by changing the config, it had full exec/write access to the workspace and overwrote the routing rules. The AGENTS.md passthrough instruction was not strong enough to prevent this.

## Fix

1. Added "NEVER do these" guard to `projects/openclaw/CLAUDE.md` — explicitly prohibits modifying AGENTS.md or SKILL.md for feature work
2. Added Test 27 to `test_delegate.sh` — catches anti-delegation text in AGENTS.md (`Process user requests directly`, `Do not delegate unless`)
3. Added Test 27 — AGENTS.md size sanity check (too short = zeroed/overwritten)
4. Added `session_used_write_on_config()` to integration tests — detects `write` tool calls to workspace config files in Gemini sessions
5. Added `session_used_non_exec_tool()` to integration tests — detects any non-exec tool use by Gemini
6. Added new red flags to `route-audit` — CRITICAL flag for write to workspace files

## Files Changed

- `/home/pranav/projects/openclaw/CLAUDE.md` — "NEVER do these" guard
- `/home/pranav/test_delegate.sh` — Test 27
- `/home/pranav/test_integration.sh` — new session helpers + Test 3b
- `/home/pranav/.local/bin/route-audit` — red flags + workspace integrity snapshot
