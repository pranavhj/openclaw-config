# OC-001 — `retry.attempts=1` not applied to embedded agent

**Type:** bug
**Status:** open
**Reported:** 2026-03-20

## Description

`openclaw.json` has `channels.discord.retry.attempts=1` but the embedded agent gateway still retries each model 4× before failing over to the next fallback. This amplifies RPM exhaustion: instead of 3 API calls (one per model), each message that hits rate limits burns 12 calls (4 retries × 3 models).

## Observed

Gateway log for runs `ceb69fc6` and `e8130ed2` (2026-03-20 ~18:20 PDT):
- gemini-2.5-flash: 4× 429 → fallback
- gemini-2.0-flash-lite: 4× 429 → fallback
- groq/llama-3.3-70b-versatile: 4× 429 → exhausted

12 total API calls, all failing. Message dropped.

## Root cause

`retry.attempts` under `channels.discord` likely applies to the **message delivery retry layer**, not the **model failover retry layer** inside the embedded agent runner. The model retry count is controlled by a different (possibly hardcoded) config path.

## Impact

High — turns a single rate-limited request into 12 burning API calls. Directly causes OC-002.

## Fix

Investigate where the embedded agent retry count is configured. Possible paths:
- `agents.defaults.retry.attempts`
- `agents.main.retry.attempts`
- Not configurable (hardcoded in embedded runner)

If not configurable, document it. If configurable, set to 1 and add to openclaw.json.
