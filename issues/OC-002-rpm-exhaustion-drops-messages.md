# OC-002 — RPM exhaustion silently drops messages when all fallbacks 429

**Type:** bug
**Status:** open
**Reported:** 2026-03-20

## Description

When all models in the fallback chain hit per-minute rate limits simultaneously, openclaw sends an "API rate limit" error to Discord (no `-# sent by claude` watermark — it comes from the gateway fallback). The message is effectively dropped but the user does receive an error notification.

## Observed

2026-03-20 ~18:20-18:26 PDT: two separate standingTableController Discord messages were dropped. Both triggered after integration test runs that consumed the RPM budget. All 3 model tiers (gemini-2.5-flash, gemini-2.0-flash-lite, groq llama-3.3-70b) 429'd simultaneously.

Root cause sequence:
1. Integration tests ran 5+ requests in <2 minutes → hit RPM limit
2. OC-001 (4× retries per model) amplified the burn: 12 wasted calls
3. standingTableController message arrived 6 minutes later, still within RPM cooldown
4. All models failed → silent drop, no Discord notification

## Impact

High — user never knows message was lost. Requires manually resending.

## Fix options

1. **Detect full-chain failure and send Discord error message** — if all models fail, use `openclaw message send` to notify the user that the message was dropped and they should resend
2. **Queue failed messages for retry after 60s cooldown** — if openclaw supports message queuing
3. **Avoid running integration tests during active usage hours** — workaround only

## Related

- OC-001 (retry amplification makes RPM exhaustion worse)
- OC-009 (first known instance of silent drop)
