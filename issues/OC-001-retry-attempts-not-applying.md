# OC-001 — `retry.attempts=1` not applied to embedded agent

**Type:** bug
**Status:** wontfix
**Reported:** 2026-03-20

## Description

`openclaw.json` has `channels.discord.retry.attempts=1` but the embedded agent gateway still retries each model 4× before failing over to the next fallback. This amplifies RPM exhaustion: instead of 3 API calls (one per model), each message that hits rate limits burns 12 calls (4 retries × 3 models).

## Observed

Gateway log for runs `ceb69fc6` and `e8130ed2` (2026-03-20 ~18:20 PDT):
- gemini-2.5-flash: 4× 429 → fallback
- gemini-2.0-flash-lite: 4× 429 → fallback
- groq/llama-3.3-70b-versatile: 4× 429 → exhausted

12 total API calls, all failing. Message dropped.

## Root cause (investigated 2026-03-20)

The retry chain has two separate layers — both confirmed by source code analysis:

**Layer 1: `@google/genai` SDK (`DEFAULT_RETRY_ATTEMPTS = 5`)**
- File: `node_modules/@mariozechner/pi-ai/dist/providers/google.js` → `createClient()` calls `new GoogleGenAI({ httpOptions })`
- File: `node_modules/@google/genai/dist/index.cjs` line 7185: `const DEFAULT_RETRY_ATTEMPTS = 5`
- The SDK retries 429/408/500/502/503/504 automatically — 4 retries after the initial call
- This is **not configurable** from openclaw.json — `pi-ai`'s `createClient()` does not pass `retryOptions` to the SDK

**Layer 2: `channels.discord.retry.attempts` (already set to 1)**
- Controls Discord message delivery retries (e.g., bot rate limits sending a message)
- Does NOT affect the embedded agent model API calls

**`AgentDefaultsSchema` has no retry config** — confirmed by reading full schema at line 8014. There is no `agents.defaults.retry.maxAttempts` or equivalent.

## Impact

Each Gemini model makes up to 5 API calls (1 initial + 4 SDK retries) before failing over. With 3 model candidates: up to 15 API calls per failed message.

## Resolution

**Not configurable** without modifying node_modules (`@mariozechner/pi-ai`). The 4 retries are intentional in the Gemini SDK for handling transient 429s from brief bursts. The problem only manifests when RPM is consistently exhausted (sustained limit, not transient burst).

Mitigation: Fix OC-002 (notify on failure) and avoid RPM exhaustion in the first place (don't run integration tests during active hours).
