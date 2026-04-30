# OC-027 -- NSSM discord-bot service logon failure

**Type:** bug
**Status:** open
**Severity:** medium

## Symptom

After a Windows reboot, `discord-bot` NSSM service remains stopped with exit code 0.
`nssm start discord-bot` returns: "The service did not start due to a logon failure."
Bot must be started manually after every reboot.

## Root Cause

The service is configured to run as `.\prana` (local user account) with a stored password.
The stored password is stale (likely changed since the service was registered).
`sc config` and `nssm set` both return "Access is denied" -- fixing requires an elevated terminal.

## Fix (permanent -- needs admin)

Open an elevated terminal and run:
```
nssm set discord-bot ObjectName LocalSystem
nssm start discord-bot
```
This switches the service to run as LocalSystem, eliminating the password requirement.

## Workaround (no admin)

Run bot manually after each reboot:
```
python D:\MyData\Software\openclaw-config\bin\discord-bot.py
```

## Files Changed

- `docs/openclaw-architecture.md` -- documented under Known Risks
- `README.md` -- startup instructions updated
- `CLAUDE.md` -- bot start instructions updated
