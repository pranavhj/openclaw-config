# OC-028 -- Ubuntu_openclaw VM silently handling Discord messages

**Type:** bug
**Status:** fixed
**Severity:** high

## Symptom

Discord messages were being handled by an unknown agent. The Windows discord-bot NSSM
service was stopped, no Python processes were visible, yet Discord replies continued
arriving with Windows-style paths in the prompts.

## Root Cause

The `Ubuntu_openclaw` VirtualBox VM (10.0.0.66, bridged network) was auto-starting on
every Windows boot via a Startup folder shortcut:
`C:\Users\prana\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\start_openclaw_headless - Shortcut.lnk`

The shortcut ran `C:\Users\prana\openclaw_workspace\start_openclaw_headless.bat`:
```
"C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" startvm "Ubuntu_openclaw" --type headless
```

The VM ran the old Linux openclaw agent, which received Discord messages and then SSHed
into the Windows host (sshd running on Windows) to run the Windows delegate pipeline.
This produced Windows paths in prompts, masking the VM origin.

## Fix

1. Removed the startup shortcut from the Startup folder.
2. Stopped the running VM: `VBoxManage controlvm Ubuntu_openclaw acpipowerbutton`
3. Started discord-bot.py manually on Windows as the sole agent.

The VM still exists on disk but no longer auto-starts.

## Files Changed

- `C:\Users\prana\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\` -- shortcut deleted
- `docs/openclaw-architecture.md` -- Startup on Reboot section added, VM documented
