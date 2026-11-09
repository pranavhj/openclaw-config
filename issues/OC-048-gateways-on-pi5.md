# OC-048 -- `rc gateway` targets the Pi 5, not this PC

**Type:** config
**Status:** fixed
**Severity:** low

## Symptom
`rc gateway gemini|chatgpt` tried to launch the gateway scripts from a local
`gemini_gateway\service` folder and ping localhost, but the gateways moved to the Raspberry Pi 5 on 2026-10-24.

## Root Cause
`bin/rc_gateways.py` (OC-045) was written when the gateways ran on this PC.

## Fix
Ping `pi5.local:<port>/ping`; if down, `ssh pi5 sudo systemctl restart <gemini-gateway|chatgpt-gateway>`
and wait up to 90 s for /ping. Host and ssh alias overridable via `GATEWAY_PI_HOST` / `GATEWAY_PI_SSH`.
`agents/remote-control.md` updated. Also ignores `.claude/worktrees/` in git.

## Files Changed
- bin/rc_gateways.py
- agents/remote-control.md
- .gitignore
