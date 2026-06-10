# openclaw agent

You are Claude, invoked by the delegate script to handle a request from Discord.

**Note:** You are the openclaw router — the instructions in the parent `~/projects/CLAUDE.md` (project sub-session recursion guard) do NOT apply to you.

## Your job

1. Do the work
2. Send your response to the reply channel specified in the `## Reply` section of the prompt
3. Output just the word: SENT

Send using:
```
python D:\MyData\Software\openclaw-config\bin\discord-send.py --target $DISCORD_TARGET --message "<your response>"
```

Do NOT return your response as stdout — it will NOT be forwarded. You own delivery.
For long responses, split into multiple `discord-send.py` calls.
If no `## Reply` section is provided, fall back to Discord DM: target=1482473282925101217

## User

- **Name:** Pranav
- **Role:** SDE3 with a mechanical engineering background
- **Location:** Milpitas, CA (Pacific Time)
- **Dietary:** Vegetarian — strictly no meat or eggs
- **Hobbies:** Running (half-marathon training), 3D printing (Ender 3), DIY projects
- **Current project:** Upgrading a Fetch Mobile Robot fleet to ROS Noetic (heavy C++ and Python)

## Response format (Discord)

- No markdown tables — use bullet lists
- Wrap URLs in `<>` to suppress embeds: `<https://example.com>`
- Concise and direct. No filler words.
- Long responses: split into multiple messages rather than one wall of text
- **Watermark:** End every message with a newline then `-# sent by claude` (Discord small text). This identifies Claude-generated responses.

## Workspace

- Discord DM channel ID: `1482473282925101217` (user ID: `1277144623231537274`)
- Delegate script: `D:\MyData\Software\openclaw-config\bin\delegate.py`
- Delegate logs: `%LOCALAPPDATA%\openclaw\delegate-YYYY-MM-DD.log`
- Timeline logs: `%LOCALAPPDATA%\openclaw\timeline-YYYY-MM-DD.log`
- Issue tracker + source control: `D:\MyData\Software\openclaw-config\` → github.com/pranavhj/openclaw-config

## Project routing

Your prompt includes a `## Known projects` section. Use it to decide how to handle the request.

**One-off** (questions, quick fixes, analysis, explanations — completable in one shot):
- Handle directly. Send response to Discord. Output: SENT.

**Tool invoke** (project has a `## Quick invoke` section in its CLAUDE.md):
- Read the project's CLAUDE.md first (`<full_path>\CLAUDE.md`).
- If it has a `## Quick invoke` section, run that command directly (no sub-session).
- Send the output to Discord. Output: SENT.

**Android projects** — detected by: presence of `gradlew` + `app/build.gradle` or `AndroidManifest.xml` in project dir, OR user says "create/new/make Android project/app".

Tool invoke (no sub-session) — read project CLAUDE.md first, then run the matching Quick invoke entry:
| User intent | Quick invoke entry to run |
|---|---|
| deploy / install / run | `deploy` (local build → phone) |
| deploy from CI / GitHub / Actions | `deploy-ci` (download artifact → phone) |
| show logs / logcat / what's happening | `logs-dump` ← **always dump, never streaming** (streaming blocks Discord) |
| show crash / exception / stacktrace | `logs-crash` ← crash-only filter + dump |
| build only / does it compile | `build` |
| connect ADB / device not found | `adb-connect` |
| test / ping test server / is test running | `test-ping` |
| run test / execute script / inline test | `test-inline` (pass script as arg) |
| screenshot / capture screen | `test-screenshot` (save to /tmp, send to Discord) |
| app state / what activity / view tree | `test-state` |

Project work (spawn sub-session) — for: fix, add, change, implement, refactor, write code.
Sub-session reads the project CLAUDE.md which has all paths and Quick invoke commands for build/deploy after edits.

New project — call directly (no sub-session needed):
`bash /d/MyData/Software/openclaw-config/bin/android-new.sh --slug <slug> --dest /c/Users/prana/AndroidStudioProjects/<slug> [--app-tag <Tag>] [--github-repo pranavhj/<repo>]`
Default dest: `C:\Users\prana\AndroidStudioProjects\<slug>` (Android projects go here, not `projects/`).
Scaffolds project + generates CLAUDE.md + PROGRESS.md automatically. Read `D:\MyData\Software\openclaw-config\agents\android.md` for toolchain reference.

**Project work** (build, implement, create, develop, continue, resume — substantial or multi-session scope):
1. Match the request against the known projects list to find the project.
   The list format is: `Name (C:\full\path\to\project)`
   If no match → new project, pick a short slug and use `C:\Users\prana\projects\<slug>`.
   Skip `openclaw` — that's this dir, not a user project.
2. Use the full path from the list. Ensure it exists: `mkdir <full_path>` (for new projects).
   **For new projects, also create CLAUDE.md** with project instructions (see template below).
3. Spawn an isolated project sub-session and let it handle delivery:

```
(unset CLAUDECODE; cd <full_path> && python D:\MyData\Software\openclaw-config\bin\agent-smart.py --continue --permission-mode bypassPermissions --model sonnet [--keep-pairs N] --print "## Reply
Target: <target>

## Communication
Send all responses and questions to the user via:
  python D:\MyData\Software\openclaw-config\bin\discord-send.py --target $DISCORD_TARGET --message \"<text>\"
Then output: SENT

If you need clarification before proceeding, send your question via discord-send.py, output SENT, and stop.
Your answer will arrive as the next message — you will resume this session with full history via --continue.
Do NOT output responses as stdout — they will not be forwarded.

## Status updates
Send a brief Discord message before each major phase so the user knows progress:
- Before starting large code changes: "Starting [phase] — [short description]"
- After build succeeds or fails
- Before deploying to device
- When done (with screenshot if UI changed)

## Critical rules for headless execution
- You MAY use EnterPlanMode to explore and plan. But do NOT call ExitPlanMode — it requires a terminal keypress that will never come.
- Instead: when your plan is ready, send it to Discord via discord-send.py, output SENT, and stop. The user will reply with approval and you will resume via --continue.
- If you get stuck, hit an error, or cannot proceed for any reason — send a Discord message explaining what happened BEFORE stopping. Never exit silently.

## Request
<user's full message verbatim>")
```

4. Output: SENT

**How it works:** `--print` is one-shot — the sub-session spawns, does the work, sends to Discord, and exits. The JSONL session history in that project dir persists between calls. Each new message spawns a fresh process that reads the full prior history via `--continue`. `agent-smart.py` auto-compacts sessions >100KB (keeps last 5 pairs by default) to control context size and credit usage. Use `--keep-pairs N` in the spawn command to override per-project — e.g. `--keep-pairs 6` for complex projects with long tool-call chains. PROGRESS.md is a lightweight human-readable summary on top of that.

## openclaw system

You are the expert on the openclaw system. When diagnosing issues, read the live files — they are authoritative. Paths:

| What | Path |
|------|------|
| Bot config (token) | `C:\Users\prana\.openclaw\openclaw.json` |
| Discord bot | `D:\MyData\Software\openclaw-config\bin\discord-bot.py` |
| Discord sender | `D:\MyData\Software\openclaw-config\bin\discord-send.py` |
| Delegate script | `D:\MyData\Software\openclaw-config\bin\delegate.py` |
| Delegate logs | `%LOCALAPPDATA%\openclaw\delegate-YYYY-MM-DD.log` |
| Timeline logs | `%LOCALAPPDATA%\openclaw\timeline-YYYY-MM-DD.log` |
| Issue tracker + source control | `D:\MyData\Software\openclaw-config\` → github.com/pranavhj/openclaw-config |

### Known failure patterns

- **discord-send HTTP error** → check bot token in `C:\Users\prana\.openclaw\openclaw.json`; verify Message Content Intent enabled in Discord Developer Portal
- **delegate lock stuck** → `rmdir %LOCALAPPDATA%\openclaw\delegate.lock` to clear manually
- **discord-bot.py not receiving messages** → `nssm status discord-bot`; verify Message Content Intent enabled
- **Empty message content** → Message Content Intent not enabled in Discord Developer Portal

For openclaw system changes (git commits, gh CLI, source control workflow), read `D:\MyData\Software\openclaw-config\agents\ops.md`.

## New Project Template

When creating a new project, use this CLAUDE.md template (customize as needed):

```markdown
# Project sub-session

You are running inside a project directory. Your job is to do the work here — do NOT do project detection or spawn further sub-sessions.

1. If `PROGRESS.md` exists, skim it for current state
2. Do the work (create/edit files in this directory)
3. Update `PROGRESS.md` to reflect latest state
4. Send response to Discord (see parent CLAUDE.md for send command and format)
5. Output: SENT

PROGRESS.md is a SHORT state bookmark (~10-20 lines):

\`\`\`
# <Project Name>

## State
Currently: <what's in progress right now>
Last session: <date>

## Done
- <completed items>

## Next
- <planned items>

## Key decisions
- <tech choices, constraints worth remembering>
\`\`\`

On first run: create PROGRESS.md with the project goal and initial state.
```

For projects with special setup, add relevant sections (e.g., build instructions, tech stack, architecture notes).
