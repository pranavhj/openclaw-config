# openclaw-config

## State
Currently: Bot and delegate stable; Android tooling complete (see AndroidAppDev project)
Last session: 2026-06-07

## Done
- Discord bot (discord-bot.py), delegate pipeline, agent-smart.py — stable
- Android tooling pipeline built and tested (scripts, skeleton, router updates)
  → Full context in AndroidAppDev project at C:\Users\prana\projects\AndroidAppDev
- delegate.py: openclaw-config now visible as project (removed from EXCLUDE_NAMES)

## Next
- OC-027: NSSM service broken (logon failure) — bot runs manually for now
- Check ISSUES.md for open issues before starting new work

## Key decisions
- Bot runs manually: `python D:\MyData\Software\openclaw-config\bin\discord-bot.py`
- openclaw/CLAUDE.md and agents/openclaw-CLAUDE.md must stay in sync
- AndroidAppDev project is the hub for Android script maintenance work
