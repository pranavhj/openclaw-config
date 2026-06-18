# OC-032 — Nightly audit no_reply false positive

**Type:** bug
**Status:** fixed
**Severity:** high

## Symptom
Nightly audit flags `no_reply: high` on interactions that actually received a Discord reply.

## Root Cause
Two paths in `parse_router_interactions` caused false positives:

1. **delegate_reply override**: `delegate_reply` sets `has_reply=True`, but `delegate_exit` overrides it to `False` when `final_output` doesn't contain "SENT" — happens on verbose Claude responses where the truncated stdout doesn't end with SENT.

2. **SENT-only outputs skipped**: `_extract_last_reply()` in delegate.py skips trivial "SENT"-only outputs, so `delegate_reply` event is never emitted. The audit code never set `has_reply=True` from SENT-in-final_output — only used SENT to clear it.

## Fix
Changed `delegate_exit` handling: if `'SENT' in final_output`, set `has_reply=True`. Removed the override that cleared `has_reply` when SENT was absent — `delegate_reply` is now authoritative and never overridden.

## Files Changed
- `bin/nightly-audit.py` — fixed `parse_router_interactions` delegate_exit logic
