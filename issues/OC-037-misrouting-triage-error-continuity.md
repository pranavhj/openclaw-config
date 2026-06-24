# OC-037 -- Project misrouting when triage gateway errors

**Type:** bug
**Status:** fixed
**Severity:** high

## Symptom
Simple/follow-up messages were sent to the wrong project (or to `router`) when the triage
gateway timed out (decision=error, elapsed ~4094ms). For example, "Ok I like the above, but
is vision necessary or just extraction of page html is sufficient" — clearly a shaadibot
follow-up — was routed to `router` instead of `shaadibot` because triage failed and keyword
matching found no project name.

Also observed: "Ok now for some reason the bot is finding all the profiles that have
rejected me..." was misrouted to `screenreader` instead of `shaadibot`, because the full
message contained the word "screen" (e.g. "screenshot") which prefix-matched "screenreader".

## Root Cause

### Bug 1: No continuity fallback when triage errors
`discord-bot.py` routing priority was: triage slug → keyword match → router.
When triage errored, keyword matching ran on context-dependent messages that contain no
project keywords. These went to `router`.

The conversation continuity mechanism (`_last_channel_slug`) existed but was never consulted
on the path from triage-error → keyword-router. `decision` was also not declared before the
triage block, so it couldn't be checked in the routing block.

### Bug 2: "screen" prefix-matches "screenreader"
`_PREFIX_BLOCKLIST` did not include "screen". Any message containing the word "screen" (e.g.
"screenshot", "read the screen") would prefix-match the "screenreader" project via Pass 3 of
`_match_project()`.

## Fix

### discord-bot.py

1. Declare `decision = ''` before the triage block so it's accessible in the routing block.

2. After `slug = _match_project(content)`, added continuity fallback:
   - Condition: `slug == 'router' AND decision == 'error'` (triage errored, keyword also failed)
   - Check `_last_channel_slug[channel_id]` for a slug used within the last 600s
   - If found and valid, use that slug and log a `slug_continuity_fallback` timeline event

3. Added "screen" and "scree" to `_PREFIX_BLOCKLIST`.

## Files Changed
- `bin/discord-bot.py`
