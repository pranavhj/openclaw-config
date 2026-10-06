# Voice-driven Remote Control (OC-043 draft)

Goal: the user speaks (voice -> text) into Discord, e.g. "open dairy on my phone",
"continue the one where I fixed login", "make a new android project called step counter".
An LLM with an explicit capability prompt works out what to do, runs terminal commands,
and asks a short question back when unclear. Typed `rc ...` commands stay as a fast path.

## Facts this design rests on (researcher, 2026-10-05)
- Router (bin/delegate.py:460-465): Claude sonnet, bypassPermissions, STATELESS (no --continue),
  always runs in ~/projects/openclaw, 1200s timeout. Median latency ~41s (June data).
- Router history: parse_history gives last 4 pairs from timeline-<slug>-<date>.log, replies cut to
  300 chars, and the prompt tells it to use only entries tagged [openclaw] (delegate.py:416),
  so effectively no memory of its own previous question.
- Follow-up routing (discord-bot.py:1097-1126): keyword > triage slug > last non-router slug
  within 600s. A bare answer ("the login one") can be routed to a project sub-session.
- Triage: Claude haiku via llm-gateway (gateway-delegate.py:321-326) with --continue +
  bypassPermissions; text-only only by prompt. Median ~9s. Gateway is NOT running now
  (no triage since 2026-07-06; /health no reply).
- Per-slug lock: a 2nd message for a busy slug is dropped with "Still working" (no queue).
- rc_sessions.py CLI lacks: takeover, copy, stop, restore, create, roots, name->path, indexes.
- Prompt injection: user text only has ' ` and newlines replaced; router pastes it into a
  double-quoted bash --print "...".

## Design (recommended: router + one CLI + state on disk)

1. **One CLI for everything: `bin/rc.py`** (JSON out, never interactive). Subcommands:
   `projects` (names, paths, live RC flags), `roots`, `convos <project>` (indexed list with
   title/date/turns/source/live state), `live`, `open <project> [--convo N|--new]`,
   `takeover <project> --convo N`, `copy <project> --convo N`, `create <root#> <name>`,
   `stop <project>`, `restore`. Takes project NAMES (fuzzy -> returns candidates if ambiguous).
   It enforces safety itself:
   - destructive steps (takeover, create, stop) are two-phase: without `--confirm <token>` they
     only return `{"needs_confirm": true, "token": ..., "summary": ...}`; the token is stored on
     disk with a 10-min expiry and must match.
   - the LLM never calls `claude`, `taskkill` or edits ~/.claude.json directly.
2. **Pending state on disk, not in LLM memory**: `rc.py` writes `rc-pending-<channel>.json`
   (question asked, options shown, confirm token). The bot injects `python bin/rc.py pending`
   output into the router prompt, so a stateless router sees "you asked X with options A/B/C".
3. **Routing**:
   - If an rc pending question exists for the channel, the next message goes to the router with
     a dedicated slug `rc` (own lock), skipping keyword/triage/continuity.
   - Otherwise a cheap keyword prefilter (remote control, phone, app, resume, continue,
     conversation(s), session(s), new project, pick up) sends the message to slug `rc`.
   - Everything else: unchanged.
4. **Router prompt**: new `agents/remote-control.md`, read by the router for slug `rc`. Lists
   every capability with example utterances -> rc.py calls, the confirm protocol, the
   ask-one-question rule, Discord reply format, and "never call claude/taskkill directly".
5. **Typed `rc ...` commands** keep the deterministic handler (instant).

## Alternative: triage does it
Faster (~9s vs ~40s) and already has tools, but: gateway is down, its session is --continue
(grows, stale context), its prompt is tuned for routing (OC-037 regressions), and haiku is
weaker at multi-step tool use. Would need the same rc.py + on-disk pending state anyway.

## Open questions
- Latency: ~40s per spoken turn on the router; acceptable?
- Should `rc` slug use a faster/cheaper model (haiku) for the router run?
- Fix the llm-gateway outage separately (affects all triage today).
