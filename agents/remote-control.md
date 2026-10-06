# Remote Control — instructions for the openclaw router (OC-043)

The user talks in plain sentences. Your job for Remote Control requests is to **translate the
request into one `rc` command** and submit it. The Discord bot validates and runs it with tested
code and replies to the user itself (links, lists, questions). You never start, stop or kill
anything yourself.

## What Remote Control is
Claude Code sessions on this PC that the user can drive from claude.ai/code or the Claude phone
app. Each session runs in a project folder and continues one conversation.

## How to submit
```
python /d/MyData/Software/openclaw-config/bin/rc_request.py "<rc command>"
```
- It prints `QUEUED <id>` on success, or `ERROR <reason>`; on ERROR fix the command or tell the user.
- Submit **one** command per request. Then output `SENT` and stop. Do NOT also send a Discord
  message saying what you did — the bot replies. (Exception: if you need to ask a question or
  can't map the request, send that via discord-send.py instead of submitting.)
- Use project names exactly as in `## Known projects` (lowercase).

## Commands you can submit
| Command | Does |
|---|---|
| `rc <project>` | Shows that project's conversations (numbered, newest first) and asks which to resume. Starts fresh if there are none. |
| `rc <project> <n>` | Resumes conversation n of that list (1 = newest). |
| `rc <project> new` | Fresh conversation in that project. |
| `rc create <name>` | New project folder; the bot asks the user where. |
| `rc create <name> <root#>` | New project folder in root #n (see roots below), no question. |
| `rc list` | Live Remote Control sessions with links. |
| `rc stop <project>` | Stops Remote Control sessions the bot started there. If Claude terminal sessions there have Remote Control on, the bot asks the user whether to close them (`yes`; `force` for a busy/hung one). |
| `rc restore` | Brings back bot-started sessions (e.g. after a reboot). |

**Never submit** `takeover`, `copy` or a bare number — those are answers only the user can give
to the bot's own question. If the user seems to agree to a takeover, tell them to reply `yes`. The same goes for closing a terminal session: never submit `yes`/`force`. If the pending section says a close question was cancelled and the user is agreeing, submit `rc stop <project>` again so the bot re-asks, and tell them to reply `yes` (or `force` if it is hung).
**Never run** `claude`, `taskkill`, `rc_sessions.py start/...`, or edit `~/.claude.json`.

## Read-only helpers (allowed)
- Project roots for `rc create <name> <root#>`:
  `python /d/MyData/Software/openclaw-config/bin/rc_request.py --roots`
- A project's conversations, in the same order the bot numbers them (JSON, newest first):
  `python /d/MyData/Software/openclaw-config/bin/rc_sessions.py convos "<full_project_path>"`
  (always use forward-slash paths in Bash — backslashes get stripped)
  Use this when the user describes a specific conversation ("the one where I fixed login") so
  you can submit `rc <project> <n>` directly. If no title clearly matches, submit `rc <project>`
  and let the bot show the list.

## Is this a Remote Control request?
Yes when the user wants to work on something **from the phone/app/claude.ai**, mentions remote
control, asks what sessions/conversations exist or are running, wants a session started,
resumed, stopped or restored, or wants a new project "set up" to work on remotely — or when the
prompt has a `## Pending Remote Control question` they are answering.

No (normal project work) when they ask you to *do* coding work ("continue fixing the dairy
tests", "resume the refactor") without any of the cues above.

If it could be either, ask **one** short question via discord-send.py, e.g.
"Do you want me to work on dairy from here, or open a dairy session on your phone?" — then SENT.

## Mapping examples
| User says | Submit |
|---|---|
| "open dairy so I can continue on my phone" | `rc dairy` |
| "pick up the dairy chat where I was fixing login" | read convos; if #2 is "Fix login bug" → `rc dairy 2`; else `rc dairy` |
| "start a fresh shaadibot session" | `rc shaadibot new` |
| "what's running on remote control?" / "show my sessions" | `rc list` |
| "shut down the cricket one" | `rc stop cricketapp` |
| "bring everything back" (after a reboot) | `rc restore` |
| "make a new android project called step counter" | NOT `rc create`: scaffold with android-new.sh (see **New project** in CLAUDE.md), then submit `rc step-counter new` |
| "new project called budget tool" (no location) | `rc create budget-tool` (bot asks where) |
| "the second one" with a pending conversation list | `rc <project from pending> 2` |
| "the android folder" with a pending create question | `rc create <name> <n of AndroidStudioProjects>` |
| "the new one" with a pending conversation list | `rc <project> new` |

## Rules for names and locations
- Project names: lowercase, spaces → `-`, only letters, digits, `_ . -`
  ("Step Counter" → `step-counter`). If the name is unclear, ask.
- New **Android** projects always go through android-new.sh (real app skeleton), followed by
  `rc <slug> new`. Use `rc create` for every other kind of new project.
- Locations: android / android studio → AndroidStudioProjects; python / pycharm →
  PycharmProjects; unity / game → UnityProjects; "software" / D drive → D:\MyData\Software;
  "projects" or unspecified → let the bot ask (omit root#).
- Fuzzy project names: map to the closest name in `## Known projects` only when it is clearly
  the same ("shaadi bot" → `shaadibot`, "cricket" → `cricketapp`). If two could match, submit
  `rc <the words they used>` — the bot lists the candidates and asks.
