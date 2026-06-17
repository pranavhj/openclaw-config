# OC-031 -- Nightly audit 6/16 followups: silent API errors, rate limit forwarding, stdout severity

**Type:** bug
**Status:** fixed
**Severity:** high

## Symptom

Nightly audit for 2026-06-16 revealed three issues:
1. When Anthropic API returned 529 overloaded errors, delegate.py logged `llm_gateway_down` and set `output='SENT'` without notifying the user — complete silence.
2. When the user hit Claude rate limits (exit 1, output contains "You've hit your limit · resets 8:40pm"), the delegate fell through to the generic "Delegation failed (exit 1)" message, losing the helpful reset-time info.
3. `stdout_forward` was flagged as `medium` severity in nightly-audit.py, but delegate.py already forwards stdout to Discord — the user still gets the reply.

## Root Cause

1. **llm_gateway_down**: The suppression block intentionally avoided a notification (to reduce noise during outages) but left the user completely in the dark.
2. **Rate limit**: No specific detection — rate limit error strings fell through to the generic failure handler which discarded the reset time.
3. **stdout_forward severity**: The event description said "Claude printed to stdout instead of discord-send" which implied the user got nothing. In reality, delegate.py forwards it and the user receives the reply.

## Fix

1. **delegate.py** (`llm_gateway_down` block, ~line 628): Added `discord_send()` call before setting `output='SENT'` — sends "Claude API is overloaded right now. Please try again in a few minutes."
2. **delegate.py** (failure handler, before generic fallback): Added rate limit detection (`hit your limit`, `you've hit`, `usage limit exceeded`). Extracts lines containing reset time and forwards them verbatim to Discord.
3. **nightly-audit.py** (~line 506): Changed `stdout_forward` severity from `medium` to `low`; updated message to "Claude printed to stdout — forwarded by delegate".
4. **agents/openclaw-CLAUDE.md** (New Project Template, step 4): Added explicit `discord-send.py` command and "do NOT output as stdout" warning to project CLAUDE.md template.

Also confirmed: Router 300s timeout was already raised to 1200s (all slugs) in commit 715e71d.

## Files Changed

- `bin/delegate.py` — llm_gateway_down notify + rate limit detection
- `bin/nightly-audit.py` — stdout_forward severity low
- `agents/openclaw-CLAUDE.md` — New Project Template no-stdout warning
- `C:\Users\prana\projects\openclaw\CLAUDE.md` — synced from agents/openclaw-CLAUDE.md
