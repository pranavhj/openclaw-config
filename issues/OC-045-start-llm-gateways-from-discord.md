# OC-045 -- Start Gemini / ChatGPT gateways from Discord

**Type:** feature
**Status:** fixed
**Severity:** low

## Symptom
No way to start the Gemini (port 18790) or ChatGPT (port 18791) gateways from Discord. User wants
both `rc gateway ...` commands and plain sentences ("please start the Gemini gateway") to work.

## Root Cause
Feature not built. A first attempt was left uncommitted in the main checkout with a bug: two
`'\n'` escapes in `discord-bot.py` had become literal newlines (SyntaxError, so the bot would not
start on its next restart). Those edits were backed up, reverted there, and redone here.

## Fix
- `bin/rc_gateways.py` (new): `resolve`, `status`, `start`. `start` checks `/ping` first, else
  launches `C:\Users\prana\AndroidStudioProjects\gemini_gateway\service\<gateway>.py` detached
  (log: `%LOCALAPPDATA%\openclaw\<key>-gateway.log`), waits up to 45s for `/ping`.
- `bin/rc_commands.py`: parses `rc gateway <gemini|chatgpt|gpt|openai> [start|status]` and
  `rc gateway status`; `gateway` is a reserved name.
- `bin/discord-bot.py`: `_rc_gateway` runs start/status and replies; logs `gateway_start`
  to the timeline.
- `agents/remote-control.md`: command rows + sentence examples for the router.
- `agents/openclaw-CLAUDE.md`: the Remote Control trigger now covers gateway requests, and gateway
  status questions are exempt from the "questions are one-off" rule.

## Files Changed
- bin/rc_gateways.py
- bin/rc_commands.py
- bin/discord-bot.py
- tests/test_rc_commands.py
- agents/remote-control.md
- agents/openclaw-CLAUDE.md
