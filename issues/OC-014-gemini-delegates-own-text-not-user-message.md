# OC-014 — Gemini passes its own composed text to delegate instead of original user message

**Type:** bug
**Status:** fixed
**Severity:** medium

## Symptom
Gateway log shows exec(delegate) called with Gemini's own generated text rather than the user's original message. Example: user said "yes please give me the calibrations"; Gemini delegated "Could you please clarify what you mean by calibrations in this context? Ive been delegating your requests to this channel, so I dont have direct access to run commands or files on your system to get calibrations."

Claude compensated via `--continue` session context and responded correctly, but the message Gemini sent was wrong.

## Root Cause
Gemini, with accumulated session context from prior turns, would compose a response to the user first (as if handling it in Mode 1), realize it couldn't, then call exec(delegate) — but with its own composed text as the message argument instead of the original user message verbatim.

## Fix
Added explicit instruction to both BOOT.md and AGENTS.md Mode 2 section:
> Pass the user's message **VERBATIM** as the message argument — do NOT compose, summarize, paraphrase, or add your own text.

## Files Changed
- `/home/pranav/.openclaw/BOOT.md`
- `/home/pranav/.openclaw/workspace/AGENTS.md`
