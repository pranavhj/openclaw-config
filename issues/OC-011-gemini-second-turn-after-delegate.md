# OC-011 — Gemini does a second model turn after exec delegate returns

**Type:** bug
**Status:** fixed
**Reported:** 2026-03-20
**Fixed:** 2026-03-20

## Description

After exec(delegate ...) returned SENT, Gemini was required to run the quota footer (`python3 /home/pranav/gemini_counter.py`) and output text. This forced a second model API call. When that call hit a rate limit, the gateway sent an "API limit" error to Discord — even though Claude had already delivered the response successfully.

Result: user saw two messages on Discord:
1. Claude's response (with `-# sent by claude`)
2. Gateway error "API rate limit" (no watermark, from gateway's fallback system)

## Root cause

BOOT.md and AGENTS.md both had a mandatory quota footer after every response, including after delegate. This required Gemini to:
1. Call exec(delegate) — first model turn ✓
2. Receive SENT result → call exec(gemini_counter.py) → output text — second model turn ✗ (rate limit)

The second turn is unnecessary: Claude already sent the response and delivery is confirmed via SENT.

## Fix

Removed the mandatory quota footer from the Mode 2 (delegate) path in both BOOT.md and AGENTS.md:
- `After exec returns SENT, stop immediately. Output nothing. Do not run any further commands.`
- Quota footer retained only for Mode 1 responses (greetings, /quota, /gemini_requests)

## Effect

Gemini's turn ends as soon as exec(delegate) returns SENT. No second model call needed. No gateway error message sent to Discord. Token usage per delegation: 1 model turn instead of 2.
