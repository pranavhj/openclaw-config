# OC-009 — standingTableController message silently dropped (quota exhaustion)

**Type:** bug
**Status:** fixed (resend required)
**Reported:** 2026-03-20

## Description

Discord message "Let's create a new project called standingTableController, it's a Python project using TCP socket to talk to a standingTableServer" was silently dropped twice (17:54 PDT and 18:25 PDT on 2026-03-20).

## Root cause

Both drops were caused by RPM exhaustion from integration test runs immediately preceding each message:
- 17:54 drop: integration tests ran ~17:30-17:45 → RPM exhausted → all fallbacks 429
- 18:25 drop: integration tests ran ~18:19 → 6 minutes later message hits remaining RPM throttle

OC-001 (4× retries per model) amplified the burn: each failed message consumed 12 API calls instead of 3.

## Fix for future

See OC-001 (reduce retry count) and OC-002 (notify user on full-chain failure).

## Status

Message needs to be resent. Daily token quota has capacity (220k/1M used as of 18:29 PDT).
Resend when >2 minutes have elapsed since last integration test run.
