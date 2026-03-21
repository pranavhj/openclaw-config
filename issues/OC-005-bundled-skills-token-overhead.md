# OC-005 — 55 bundled skills inflate every Gemini prompt by ~2500 tokens

**Type:** feature
**Status:** fixed
**Reported:** 2026-03-20
**Fixed:** 2026-03-20

## Description

All 55 openclaw built-in skills (apple-notes, spotify, openhue, 1password, etc.) were included in every Gemini model turn as tool definitions, consuming ~2500 tokens per request that Gemini would never use.

Observed: 184,893 input tokens / 47 requests = ~3,934 tokens/request average.

## Fix

Set `skills.allowBundled: ["__none__"]` in `openclaw.json` (see OC-003 for the correct syntax).

After fix: only 5 workspace skills loaded (delegate, discord-send, gemini-requests, quota, routing-audit).
Estimated: ~1,200-1,500 tokens/request — ~60-65% reduction.
