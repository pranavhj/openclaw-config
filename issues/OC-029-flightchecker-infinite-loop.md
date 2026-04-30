# OC-029 -- flightchecker infinite loop hangs delegate

**Type:** bug
**Status:** fixed
**Severity:** high

## Symptom

After asking a flight query via Discord ("can we do the same search for flights from SFO
to Vegas"), the delegate lock never released. All subsequent Discord messages were blocked
with "Still working on a previous task." The stuck processes were:
- PID 25452: `python -m flightchecker` (infinite scheduler loop)
- PID 25464: `claude` (waiting for flightchecker to return)
- PID 11216: `agent-smart.py` (waiting for claude)
- PID 21324: `delegate.py` (waiting for agent-smart)

## Root Cause

The openclaw haiku routing agent invoked `python -m flightchecker` without the `--once`
flag. Without `--once`, `main()` enters an infinite scheduler loop (`while True: sleep(30)`)
and never returns. The haiku agent read `main.py` with `limit: 50`, truncating before the
argument parser definition, so it never saw the `--once` flag. The session had grown to
316KB (single run) making it hard for the model to retain CLAUDE.md guidance.

## Fix

1. **`flightchecker/main.py`**: Inverted the default -- bare invocation now runs once and
   exits. The scheduler loop requires an explicit `--schedule` flag.
   `if args.once or not args.schedule: _run_once(...); return`

2. **`flightchecker/CLAUDE.md`**: Added prominent CRITICAL warning and `## Quick invoke`
   section for agent use.

3. **`openclaw/CLAUDE.md`**: Added generic "Tool invoke" routing rule -- if a project's
   CLAUDE.md has a `## Quick invoke` section, the router runs that command directly without
   spawning a `--continue` sub-session. This keeps history from growing across repeated
   flight queries and prevents the haiku from doing exploratory work inline.

4. **Cleared stuck processes**: PIDs 25452, 25464, 11216, 21324 killed.
   Delegate lock cleared: `rmdir %LOCALAPPDATA%\openclaw\delegate.lock`

## Files Changed

- `C:\Users\prana\projects\flightchecker\flightchecker\main.py`
- `C:\Users\prana\projects\flightchecker\CLAUDE.md`
- `C:\Users\prana\projects\openclaw\CLAUDE.md`
- `agents/openclaw-CLAUDE.md`
- `docs/openclaw-architecture.md`
