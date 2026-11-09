# OC-047 -- Late answer to the `rc <project>` picker went to the router

**Type:** bug
**Status:** fixed
**Severity:** medium

## Symptom
2026-11-09: "Claudeinfra remote control" -> bot listed claudeInfra conversations at 15:35:57.
The user replied `0` (new conversation) at 15:50:02. No session started; the router answered
"Got "0" -- not sure what you mean". A second `0` hit triage HTTP 409 / "router busy".

## Root Cause
The picker question (`_rc_pending`) expired after 10 min (`PENDING_TTL_S = 600`). The reply came
14 min later, so `rc_commands.parse` ignored it, the stale question was dropped, and `0` was
routed as a fresh message with no context.

## Fix
- Number pickers (`convo`, `create`) now stay open 1 hour (`PICK_TTL_S`). Takeover/close
  questions keep 10 min. Any other message still closes the picker, so a stray number can't act on it.
- A bare number sent after a picker expired (within 24 h, and with no message in between) gets
  `pick_expired`: the bot replies "That list expired... send `rc <project>` again" instead of
  sending it to the router.

## Files Changed
- bin/rc_commands.py
- bin/discord-bot.py
- tests/test_rc_commands.py
