# OC-042 -- Start the Discord bot at boot without login

**Type:** config
**Status:** open
**Severity:** high

## Symptom
After a reboot the bot did not come back: the NSSM service `discord-bot` fails with
"StartService FAILED 1069: logon failure" (OC-027), so the bot was being run by hand.
`restart-bot.py` (sc stop/start) stopped the service and could not start it again.

## Root Cause
The Windows account `prana` is a Microsoft account (`Get-LocalUser prana` ->
PrincipalSource MicrosoftAccount). Anything that logs on without the user present must use
the Microsoft account password, not the Windows Hello PIN; a wrong/PIN password produces
error 1069 (most likely cause of OC-027 -- not confirmed).

## Fix
- `bin/run-bot.cmd`: restart loop around discord-bot.py; output appended to
  `%LOCALAPPDATA%\openclaw\bot.log` (rotated at 5 MB); uses `ping` for the delay because
  `timeout` fails without a console.
- `bin/install-bot-autostart.ps1` (run once as administrator): Task Scheduler task
  `OpenclawDiscordBot` -- at startup (+30s), run whether logged on or not as this account
  (password stored by Task Scheduler), no time limit, restart on failure; disables the NSSM
  service; replaces any manual bot with the task-managed one.
- `bin/restart-bot.py`: ends the discord-bot.py process (run-bot.cmd restarts it); starts the
  task if nothing is running. No longer uses sc/NSSM.

Verified (2026-10-05, without the task): run-bot.cmd started via WMI ran the bot; restart-bot.py
ended it and the loop restarted it (ready after 19s). The task itself needs the admin step.

## Installed (2026-10-05)
- First attempt failed with 0x8007052E (wrong password) and the script continued, stopping the
  running bot; fixed: `$ErrorActionPreference='Stop'` + 3 password attempts before any change.
- Second attempt succeeded: task runs as PRANAVHP\prana (LogonType Password); bot runs in
  session 0 and connected; NSSM service discord-bot is Disabled.
- restart-bot.py now uses the bot's restart-bot.signal file (works across sessions; a
  non-admin process cannot see session-0 command lines). Verified: exit 0 -> run-bot.cmd
  restart -> ready after 19s.

## Pending
- Reboot test: bot ready in bot.log without logging in.

## Files Changed
- bin/run-bot.cmd (new)
- bin/install-bot-autostart.ps1 (new)
- bin/restart-bot.py
- agents/openclaw-CLAUDE.md (troubleshooting line)
