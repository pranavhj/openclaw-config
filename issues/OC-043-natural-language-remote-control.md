# OC-043 -- Natural-language Remote Control requests

**Type:** feature
**Status:** fixed
**Severity:** medium

## Symptom
Remote Control (OC-041) needed exact `rc ...` commands. The user wants to write plain
sentences ("open dairy so I can keep going on my phone") and have them understood, with a
question back when unclear.

## Root Cause
The router only knew to reply with an `rc` command for the user to type. Design and adversarial
review: plan/nl-rc-design.md (letting the LLM execute directly was rejected: no real consent,
keyword prefilter hijacks project work, answers dropped while busy).

## Fix
The LLM only translates; the bot validates and executes with the tested OC-041 code.
- `bin/rc_request.py`: router submits one `rc ...` string (single line, <=3 words after rc);
  atomic JSON file in %LOCALAPPDATA%\openclaw\rc-requests\. `--roots` lists project roots.
- `discord-bot.py` `watch_rc_requests`: polls the dir, rejects stale (>5 min), non-DM/other
  channels, invalid commands and consent actions (takeover/copy/pick), runs the rest via
  `_handle_rc` and replies in the DM. Forces a project rescan first (router may have just
  created the project).
- Open bot questions: a non-number reply goes to the router once, with the question + options
  injected (`OPENCLAW_RC_PENDING` -> delegate.py prompt section), skipping triage, keyword and
  continuity routing; the bot waits up to 60s if the router is still finishing. Topic switches
  are handled by the router as normal requests.
- `rc_commands`: `rc create <name> <root#>`; "yes"-style replies answer the takeover question
  (user-typed only); `pending_context()`; pending kinds now carry labels/candidates.
- Router prompt: new **Remote Control** intent -> reads `agents/remote-control.md` (capabilities,
  submit protocol, examples, name/location rules, RC vs project-work rule); question-style
  RC requests exempted from the one-off rule; new Android projects -> android-new.sh then
  `rc <slug> new`.
- Router repo: `.claude/state/` ignored -- hook state there made the global clean-tree Stop gate
  block router runs ("I'll wait for your choice" outputs).

## Verification
- Unit: test_rc_commands 65/65, test_rc_request 14/14, test_rc_sessions 52/52.
- Bot smoke (fake DM): accept/reject/stale/wrong-channel/candidates/bad-root paths.
- Real router eval (sonnet, real prompt, 10 sentences): 10/10 (one deferred an ambiguous
  "cricket" to the bot's candidate list, which is the intended behaviour); 11-44s per turn.

## Review round (2026-10-05) -- SOUND WITH CAVEATS, fixes applied
- Stop-candidates answer kept the stop action (pending stores `action`; context says rc stop).
- Takeover question caused by a router request is `strict`: only a plain "yes"/"takeover" consents.
- Topic switch: a reply naming an unrelated project drops the rc context and routes normally;
  `!` replies ignore the rc question.
- Router still busy after 60s: the rc question is restored so the resend keeps its context.
- Requests: `source` must be router; max 5 per minute; DM recipient must be known.
- A late router request no longer wipes an open takeover question.

## Files Changed
- bin/rc_request.py (new), agents/remote-control.md (new), tests/test_rc_request.py (new)
- bin/discord-bot.py, bin/delegate.py, bin/rc_commands.py, bin/run-tests.py
- agents/openclaw-CLAUDE.md (+ router repo CLAUDE.md, .gitignore)
- tests/test_rc_commands.py
