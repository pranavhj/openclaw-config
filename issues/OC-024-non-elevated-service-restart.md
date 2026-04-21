# OC-024 — Non-elevated Service Restart

**Type:** feature
**Status:** fixed
**Severity:** medium

## Symptom
Claude (running as user `prana`) cannot restart the `discord-bot` NSSM service because NSSM
services are protected — `nssm restart`, `sc stop/start`, and `Stop-Process` on NSSM/Python
processes all return "Access is denied" from a non-elevated context.
User had to run an admin PowerShell manually every time the bot needed a restart.

## Root Cause
The `discord-bot` Windows service runs under `LocalSystem` (SYSTEM). By default only
`BUILTIN\Administrators` have `SERVICE_START` / `SERVICE_STOP` rights in the service's
security descriptor. The current user (`prana`) is not in that group for service control.

## Fix

### One-time admin setup: `manage-service.ps1 grant-user`

New action added to `manage-service.ps1`:
- Reads the current service SDDL with `sc sdshow discord-bot`
- Derives the current user's SID via `[NTAccount]::Translate(SecurityIdentifier)`
- Prepends ACE `(A;;CCLCSWRPWPDTLOCRRC;;;SID)` to the existing DACL:
  - `CC` = SERVICE_QUERY_CONFIG
  - `LC` = SERVICE_QUERY_STATUS
  - `SW` = SERVICE_ENUMERATE_DEPENDENTS
  - `RP` = SERVICE_START
  - `WP` = SERVICE_STOP
  - `DT` = SERVICE_PAUSE_CONTINUE
  - `LO` = SERVICE_INTERROGATE
  - `CR` = SERVICE_USER_DEFINED_CONTROL
  - `RC` = READ_CONTROL
- Applies via `sc sdset discord-bot <new_sddl>`
- Idempotent: skips if ACE already present

### `bin/restart-bot.py` (new)

Non-elevated restart script Claude can call directly:
1. Queries current service state
2. If `STOP_PENDING`: waits up to 15s for it to clear naturally (common case)
3. If `RUNNING`: issues `sc stop`, waits for `STOPPED`
4. Issues `sc start`, waits up to 20s for `RUNNING`
5. Exits 0 on success, 1 on failure with diagnostic message

## Setup Instructions (one-time, admin)

```powershell
# In an elevated PowerShell:
D:\MyData\Software\openclaw-config\bin\manage-service.ps1 grant-user
```

## Usage (non-elevated, from Claude)

```
python D:\MyData\Software\openclaw-config\bin\restart-bot.py
```

## Limitation

If the service is stuck in `STOP_PENDING` due to a SYSTEM-owned NSSM process that won't exit,
`restart-bot.py` will wait 15s and then report the issue. This edge case still requires a
one-time admin intervention to clear. Normal stop/start cycles work fully non-elevated
after `grant-user` is run.

## Files Changed
- `bin/manage-service.ps1` (grant-user action)
- `bin/restart-bot.py` (new)
- `tests/test_delegate.py` (section 29, restart-bot.py in ALLOWED)
