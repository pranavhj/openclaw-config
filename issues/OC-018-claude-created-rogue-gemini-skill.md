# OC-018 — Claude created rogue Alexa skill in Gemini workspace

**Type:** bug
**Status:** fixed
**Severity:** high

## Symptom

2026-03-23 ~12:54 PDT: User asked "Can you write a client so openclaw can talk to Alexa." Claude (openclaw agent) handled the delegation correctly, built the `alexa-controller` project in `projects/alexa-controller/`, but also:

1. Created `/home/pranav/.openclaw/workspace/skills/alexa/SKILL.md` — a Gemini skill with `alexa-send` exec commands
2. Created `/home/pranav/.local/bin/alexa-send` — a wrapper binary for Gemini to call directly

This means future Alexa requests would be handled by Gemini directly via `exec(alexa-send ...)` instead of being delegated to Claude. Bypasses the entire delegation architecture.

## Root Cause

Claude's CLAUDE.md did not explicitly prohibit creating Gemini skills. When tasked with "openclaw integration," Claude defaulted to the pattern of creating a skill + exec wrapper — which is the correct pattern for openclaw built-in features (quota, gemini-requests) but wrong for user-facing projects. User projects should always be handled via delegation, not Gemini exec.

## Fix

1. Deleted `/home/pranav/.openclaw/workspace/skills/alexa/` (rogue skill)
2. Deleted `/home/pranav/.local/bin/alexa-send` (rogue binary)
3. Added "NEVER do these" guard to `projects/openclaw/CLAUDE.md`:
   - Do NOT create Gemini skills (`workspace/skills/<anything>/SKILL.md`) for user features
   - Do NOT create exec binaries in `~/.local/bin/` for Gemini to call
   - Skills allowed: delegate, discord-send, quota, gemini-requests, routing-audit — that's it
4. Added Test 25 to `test_delegate.sh` — skill allowlist check (fails on any skill beyond the 5 allowed)
5. Added Test 26 to `test_delegate.sh` — binary allowlist check (`~/.local/bin/`)
6. Added Test 3b to `test_integration.sh` — workspace + binary integrity check on every integration run
7. Added workspace integrity snapshot to `route-audit` — reports rogue skills/binaries in daily audit

## Files Changed

- `/home/pranav/projects/openclaw/CLAUDE.md` — "NEVER do these" guard
- `/home/pranav/test_delegate.sh` — Tests 25 and 26
- `/home/pranav/test_integration.sh` — Test 3b
- `/home/pranav/.local/bin/route-audit` — workspace integrity snapshot
