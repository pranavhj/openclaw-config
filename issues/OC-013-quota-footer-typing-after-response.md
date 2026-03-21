# OC-013 — Quota footer exec causes typing indicator after Claude responds

**Type:** bug
**Status:** fixed
**Severity:** medium

## Symptom
"OpenClaw Agent is typing..." appears in Discord for 5–10 seconds after Claude's response is already visible.

## Root Cause
`AGENTS.md` had a `## Quota Footer` section instructing Gemini to run `python3 /home/pranav/gemini_counter.py` after every response. Despite the note "Do NOT run after delegate," Gemini ran it anyway after every Mode 2 delegation. The script queries Google Cloud Monitoring API (~5–10s), keeping the Gemini turn open and the typing indicator active long after Claude had already sent the message.

Additionally, accumulated session history showed Gemini running the quota footer after delegation, reinforcing the behavior even as instructions were updated.

## Fix
- Removed the entire `## Quota Footer` section from `AGENTS.md`. BOOT.md never mentioned it.
- Cleared the accumulated Gemini session (45KB, 10 turns of old behavior).

## Files Changed
- `/home/pranav/.openclaw/workspace/AGENTS.md`
