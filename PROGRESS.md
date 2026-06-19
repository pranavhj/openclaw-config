# openclaw-config

## State
Currently: Bot and delegate stable; architecture fixes deployed (OC-034)
Last session: 2026-06-19

## Done
- Discord bot (discord-bot.py), delegate pipeline, agent-smart.py — stable
- Android tooling pipeline built and tested (scripts, skeleton, router updates)
  → Full context in AndroidAppDev project at C:\Users\prana\projects\AndroidAppDev
- delegate.py: openclaw-config now visible as project (removed from EXCLUDE_NAMES)
- OC-033: Triage improvements — removed 10-min timeouts, always use gateway, opus model, attachment skip
- OC-034: Architecture fixes — gateway log date UTC→local, ALLOWED_USER from config, project discovery consolidated, discord-send retry

## Next
- OC-027: NSSM service broken (logon failure) — bot runs manually for now
- Check ISSUES.md for open issues before starting new work

## Key decisions
- Bot runs manually: `python D:\MyData\Software\openclaw-config\bin\discord-bot.py`
- openclaw/CLAUDE.md and agents/openclaw-CLAUDE.md must stay in sync
- AndroidAppDev project is the hub for Android script maintenance work
