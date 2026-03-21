# openclaw System Architecture
_Last updated: 2026-03-21_

---

## Message Flow (End-to-End)

```
┌─────────────────────────────────────────────────────────────────┐
│                     INBOUND CHANNELS                            │
│                                                                 │
│   Discord DM ──────────────────┐                               │
│   (allowFrom: 1277144623231537274)                             │
│                                │                               │
│   openclaw CLI ────────────────┤──► openclaw gateway           │
│                                │    port 18789                 │
└────────────────────────────────┼────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                      GEMINI (agent:main)                        │
│                                                                 │
│  Model: google/gemini-2.5-flash                                │
│  Fallbacks: none                                                │
│  Workspace: /home/pranav/.openclaw/workspace/                   │
│  Skills: 5 workspace only (55 bundled disabled via             │
│          allowBundled: ["__none__"])                            │
│                                                                 │
│  Reads on startup:                                              │
│    BOOT.md     → routing rules (Mode 1/2)                      │
│    AGENTS.md   → routing rules, group chat etiquette           │
│    (session resets after 5min idle — stateless router)          │
│                                                                 │
│  ┌─────────────────────────────────────────────────┐           │
│  │  MODE 1 — Trivial (Gemini handles itself)        │           │
│  │  • Greetings, "hi", "thanks"                    │           │
│  │  • HEARTBEAT_OK                                  │           │
│  │  • /quota, /gemini_requests (exec-dispatch)      │           │
│  └─────────────────────────────────────────────────┘           │
│                                                                 │
│  ┌─────────────────────────────────────────────────┐           │
│  │  MODE 2 — Delegate (all non-trivial requests)   │           │
│  │  Loads delegate skill → runs exec               │           │
│  │  exec({command: 'delegate <ch> <tgt> <msg>',    │           │
│  │         yieldMs: 120000})                       │           │
│  │  Stops immediately after exec returns any result │           │
│  └─────────────────────────────────────────────────┘           │
│                                                                 │
│  Mode 1 only: quota footer python3 gemini_counter.py           │
└─────────────────────────────────────────────────────────────────┘
                    │ Mode 2
                    │ exec(command: 'delegate ...')
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│              /home/pranav/.local/bin/delegate                   │
│                                                                 │
│  1. Acquire lock: /tmp/openclaw/delegate.lock (mkdir atomic)   │
│     └─ If locked → echo SENT, exit (prevents duplicate runs)   │
│  2. Collect context:                                            │
│     • Projects list: ls /home/pranav/projects/                 │
│  3. Build prompt in temp file (handles special chars safely)    │
│  4. Run Claude:                                                 │
│     cd /home/pranav/projects/openclaw                          │
│     agent --continue --permission-mode bypassPermissions        │
│            --print "$(cat $PROMPT_FILE)"                        │
│  5. Log result to /tmp/openclaw/delegate-YYYY-MM-DD.log        │
│  6. Echo output (openclaw sees "SENT")                         │
└─────────────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│         openclaw_claude (Claude) — projects/openclaw/           │
│                                                                 │
│  Working dir: /home/pranav/projects/openclaw/                  │
│  Config: /home/pranav/projects/openclaw/CLAUDE.md              │
│  Session: --continue (persists across conversations)            │
│                                                                 │
│  Receives prompt with:                                          │
│    ## Reply  (channel + target for response delivery)           │
│    ## Known projects (list from /home/pranav/projects/)         │
│    ## Request (user's full message verbatim)                    │
│                                                                 │
│  ┌─────────────────────────────────────────────────┐           │
│  │  ONE-OFF request (question, analysis, fix)       │           │
│  │  → Handle directly                               │           │
│  │  → openclaw message send to Discord              │           │
│  │  → Output: SENT                                  │           │
│  └─────────────────────────────────────────────────┘           │
│                                                                 │
│  ┌─────────────────────────────────────────────────┐           │
│  │  PROJECT request (build/implement/continue)      │           │
│  │  → Match slug in known projects list             │           │
│  │  → mkdir -p /home/pranav/projects/<slug>         │           │
│  │  → Spawn isolated sub-session:                   │           │
│  │    cd projects/<slug> &&                         │           │
│  │    agent --continue --print "..."                │           │
│  │  → Sub-session handles delivery + outputs SENT   │           │
│  └─────────────────────────────────────────────────┘           │
│                                                                 │
│  Also knows (openclaw expert):                                  │
│    • All skill paths and purposes                               │
│    • Issue tracker: /home/pranav/openclaw-config/ISSUES.md      │
│    • Source control workflow (sync + commit after edits)        │
│    • Test scripts and how to run them                           │
│    • Session log format + routing failure patterns              │
│    • Gateway config and key diagnostic info                     │
└─────────────────────────────────────────────────────────────────┘
         │ one-off                    │ project work
         │                           ▼
         │              ┌────────────────────────────┐
         │              │  Project sub-session        │
         │              │  (Claude in projects/<slug>)│
         │              │                             │
         │              │  Config: inherits from      │
         │              │  projects/CLAUDE.md +       │
         │              │  /home/pranav/CLAUDE.md     │
         │              │                             │
         │              │  • Reads PROGRESS.md        │
         │              │  • Does the work            │
         │              │  • Updates PROGRESS.md      │
         │              │  • Sends to Discord         │
         │              │  • Exits (one-shot)         │
         │              │  • Session history persists │
         │              │    in JSONL for next call   │
         │              └────────────────────────────┘
         │                           │
         └───────────────────────────┘
                                     │
                    openclaw message send --channel <ch> --target <tgt>
                                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                   OUTBOUND DELIVERY                             │
│                                                                 │
│   Discord DM ──── channel=discord, target=1482473282925101217   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Special Paths (bypass delegate)

```
User: "run tests" / "check routing"
    │
    ▼
Gemini loads routing-audit skill
    │
    ▼
exec({command: 'run-tests'})
    │
    ▼
/home/pranav/.local/bin/run-tests
  • SKIP_GATEWAY_RESTART=1
  • Runs test_delegate.sh       → unit results
  • Runs test_integration.sh    → integration results
  • Runs test_claude_behavior.sh → behavior results
  • Sends formatted summary to Discord (itself, no Claude involved)

User: "analyze logs" / "route-audit"
    │
    ▼
Gemini loads routing-audit skill → exec({command: 'route-audit'})
    │
    ▼
/home/pranav/.local/bin/route-audit
  • Gathers delegate log + gateway log + session JSONLs
  • Passes to: cd /home/pranav/projects/openclaw && agent --continue
  • Claude analyzes + sends Discord report

User: "/quota" or "/gemini_requests"
    │
    ▼
Gemini exec-dispatches directly (no delegate, no Claude):
  quota:            python3 /home/pranav/gemini_counter.py status
  gemini-requests:  /gemini_requests gq
```

---

## Source Control & Issue Tracking

```
┌─────────────────────────────────────────────────────────────────┐
│          github.com/pranavhj/openclaw-config (private)          │
│          /home/pranav/openclaw-config/  (also in ~/projects/)   │
│                                                                  │
│  Tracks: all openclaw configs, skills, scripts, agent prompts   │
│  Does NOT track: project code (standingTableController, etc.)   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  AUTO-COMMIT (systemd path watcher)                       │   │
│  │  openclaw-config-sync.path watches 12 live files:         │   │
│  │    BOOT.md, AGENTS.md, all 5 SKILL.md files,             │   │
│  │    openclaw-CLAUDE.md, projects-CLAUDE.md,               │   │
│  │    delegate, route-audit, openclaw.json                   │   │
│  │                                                           │   │
│  │  On any change → openclaw-config-sync.service runs:       │   │
│  │    1. sync-from-live.sh (redacts secrets)                 │   │
│  │    2. git add -A                                          │   │
│  │    3. git commit "sync(misc): auto-commit..."             │   │
│  │    4. git push                                            │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  INTENTIONAL COMMITS (Claude or manual)                   │   │
│  │  Format enforced by commit-msg hook:                      │   │
│  │    fix(OC-001): description                               │   │
│  │    feat(OC-008): description                              │   │
│  │    sync(misc): description                                │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  ISSUE TRACKER  (issues/OC-NNN-*.md + ISSUES.md index)   │   │
│  │  OC-001 (wontfix) retry.attempts=1 not applying          │   │
│  │  OC-002 (open)    RPM exhaustion → error msg to Discord  │   │
│  │  OC-003 (fixed)   allowBundled:[] does nothing           │   │
│  │  OC-004 (fixed)   Gemini session not cleared between turns│  │
│  │  OC-005 (fixed)   55 bundled skills inflating tokens     │   │
│  │  OC-006 (fixed)   AGENTS.md was 9.3KB                    │   │
│  │  OC-007 (fixed)   route-audit used wrong working dir     │   │
│  │  OC-008 (fixed)   no per-project session isolation       │   │
│  │  OC-009 (fixed)   standingTable dropped (quota exhaustion)│  │
│  │  OC-010 (fixed)   channel misidentification              │   │
│  │  OC-011 (fixed)   Gemini second turn after delegate      │   │
│  │  OC-012 (fixed)   Gemini second turn after exec error    │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Secrets: openclaw.json stored with ${VAR} placeholders         │
│  Credentials: token in ~/.git-credentials (not in remote URL)   │
│  Pre-commit hook: blocks real secrets from being committed       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Config Files — What Lives Where

```
/home/pranav/.openclaw/
├── openclaw.json                    ← GATEWAY CONFIG
│   • API keys (Gemini, Groq)
│   • Agent model: gemini-2.5-flash
│   • Fallbacks: none
│   • Workspace: /home/pranav/.openclaw/workspace/
│   • skills.allowBundled: ["__none__"]  ← disables all 55 bundled skills
│   • Channels: discord only (retry=1)
│   • allowFrom: user IDs (allowlist)
│   • Gateway port: 18789, auth token
│   • Tools: coding profile, web search, exec security=full
│   • session.reset.idleMinutes: 5  ← Gemini context resets after 5min idle
│
├── BOOT.md                          ← GEMINI ROUTING RULES (boot-time)
│   • Mode 1: what Gemini handles itself
│   • Mode 2: delegate via delegate skill; stop after any exec result
│
├── workspace/
│   ├── AGENTS.md                    ← GEMINI WORKSPACE INSTRUCTIONS (~1.3KB)
│   │   • Mode 1/2 routing (trimmed 86% from 9.3KB)
│   │   • Channel/target defaults (Discord DM ID)
│   │   • Group chat rules
│   │   • Heartbeat instructions
│   │
│   ├── SOUL.md                      ← Gemini identity/values
│   ├── TOOLS.md                     ← Local env notes
│   ├── HEARTBEAT.md                 ← Periodic task checklist
│   ├── memory/                      ← Gemini's daily session notes
│   │   └── YYYY-MM-DD.md
│   │
│   └── skills/                      ← WORKSPACE SKILLS ONLY (bundled disabled)
│       ├── delegate/SKILL.md        ← HOW TO CALL DELEGATE
│       │   • description frontmatter embeds exec command + yieldMs:120000
│       │   • Prevents Gemini hallucinating wrong SKILL.md paths
│       │
│       ├── routing-audit/SKILL.md   ← HOW TO RUN TESTS / AUDIT LOGS
│       ├── discord-send/SKILL.md    ← PROACTIVE DISCORD MESSAGES
│       ├── quota/SKILL.md           ← /quota COMMAND
│       └── gemini-requests/SKILL.md ← /gemini_requests gq COMMAND
│
└── agents/
    └── main/
        └── sessions/                ← GEMINI SESSION STORE
            ├── sessions.json        ← session index
            └── *.jsonl              ← auto-reset after 5min idle (idleMinutes:5)

/home/pranav/
├── CLAUDE.md                        ← DIRECT TERMINAL CLAUDE CONFIG
│   • General instructions (unchanged, clean)
│   • NOT read by openclaw-mediated calls
│
├── projects/
│   ├── CLAUDE.md                    ← PROJECT SUB-SESSION OVERRIDE
│   │   • "You're in a project dir — do the work, don't spawn sub-sessions"
│   │   • Prevents recursion when openclaw_claude spawns sub-sessions
│   │
│   ├── openclaw/
│   │   └── CLAUDE.md               ← OPENCLAW_CLAUDE CONFIG
│   │       • Job: do work, send via openclaw, output SENT
│   │       • User profile (Pranav, SDE3, Milpitas, etc.)
│   │       • Discord format: no tables, <> URLs, -# sent by claude watermark
│   │       • Project routing (one-off vs spawn sub-session)
│   │       • Source control workflow (sync + commit with OC-NNN)
│   │       • openclaw system knowledge + failure patterns
│   │
│   ├── openclaw-config -> /home/pranav/openclaw-config   ← SYMLINK
│   │   • Allows openclaw_claude to find/work on the config repo
│   │
│   └── <user-projects>/             ← Actual project work
│       ├── PROGRESS.md              ← State bookmark (Claude maintains)
│       └── <source files>
│
└── .local/bin/
    ├── delegate                     ← DELEGATION ORCHESTRATOR
    │   • Lock, logging, context gathering (projects list)
    │   • Invokes: cd projects/openclaw && agent --continue
    │
    ├── send-gemini-stats            ← GEMINI USAGE REPORTER
    │   • Runs gq, sends output to Discord
    │   • Scheduled via system crontab (no Gemini dependency)
    │
    ├── run-tests                    ← FULL TEST SUITE RUNNER
    │   • SKIP_GATEWAY_RESTART=1
    │   • Runs all 3 suites, sends Discord summary
    │
    └── route-audit                  ← LOG ANALYSIS SCRIPT
        • Gathers logs + sessions for a date
        • cd projects/openclaw && agent --continue --model claude-opus-4-6

/home/pranav/openclaw-config/        ← SOURCE CONTROL REPO
    config/openclaw.json             ← sanitized (secrets as ${VAR})
    config/BOOT.md
    workspace/AGENTS.md
    workspace/skills/*/SKILL.md
    agents/openclaw-CLAUDE.md
    agents/projects-CLAUDE.md
    bin/delegate, route-audit, run-tests
    issues/OC-NNN-*.md
    scripts/sync-from-live.sh        ← copies live → repo + redacts secrets
    scripts/sync-to-live.sh          ← deploys repo → live paths

/home/pranav/.config/systemd/user/
    openclaw-config-sync.path        ← watches 12 live config files
    openclaw-config-sync.service     ← auto-sync + commit + push on change

# System crontab
7 10-23,0-1 * * *  send-gemini-stats  ← Gemini usage stats to Discord (PT)
```

---

## Agent Responsibilities

| Agent | Model | Working Dir | Config | Responsibility |
|---|---|---|---|---|
| **Gemini** (agent:main) | gemini-2.5-flash | `.openclaw/workspace/` | BOOT.md + AGENTS.md | Stateless router: classify → load skill → exec delegate or exec-dispatch. Stops immediately after delegate exec returns. Session resets after 5min idle. |
| **openclaw_claude** | claude-sonnet-4-6 | `projects/openclaw/` | `projects/openclaw/CLAUDE.md` | Entry point for all channel traffic. One-off: handles directly. Project work: spawns isolated sub-session in project dir. |
| **Project sub-session** | claude-sonnet-4-6 | `projects/<slug>/` | `projects/CLAUDE.md` + `CLAUDE.md` | Isolated per-project Claude session. Reads PROGRESS.md, does work, updates PROGRESS.md, sends to Discord, exits. |
| **Claude Code** (terminal) | claude-sonnet-4-6 | `/home/pranav/` | `CLAUDE.md` | Direct dev work with Pranav in terminal |

---

## Skill Responsibilities

| Skill | Trigger | Action | Who Runs |
|---|---|---|---|
| **delegate** | Any non-trivial request | `exec(delegate <ch> <tgt> <msg>, yieldMs:120000)` | Gemini |
| **routing-audit** | "run tests", "check routing" | `exec(run-tests)` or `exec(route-audit)` | Gemini directly |
| **discord-send** | Proactive notifications | `exec(openclaw message send ...)` | Gemini |
| **quota** | `/quota` | `exec(python3 gemini_counter.py status)` | Gemini exec-dispatch |
| **gemini-requests** | `/gemini_requests` | `exec(/gemini_requests gq)` | Gemini exec-dispatch |

---

## Token Optimization

Per-request token breakdown (before → after):

| Source | Before | After |
|---|---|---|
| BOOT.md | ~800 | ~800 (unchanged) |
| AGENTS.md | ~2,300 | ~335 (trimmed 86%) |
| 55 bundled skill definitions | ~2,500 | 0 (disabled) |
| Gemini session history | growing | ~0 (idleMinutes:5 resets on inactivity) |
| **Total estimate** | **~3,934/req** | **~1,200–1,500/req** |

Result: ~60–65% reduction. Daily message capacity ~263 → ~650+ at 1M TPD limit.

---

## Key Design Decisions & Why

**`yieldMs: 120000` on delegate exec**
Default is 10s which backgrounds the command before Claude responds. 2 min gives Claude time to complete.

**`session.reset.idleMinutes: 5` (stateless Gemini router)**
Gemini is a pure router — it needs zero cross-turn context. `idleMinutes:5` resets the session after 5 minutes of inactivity, so most messages start fresh. Prior approach (truncating the JSONL mid-turn) was a no-op: openclaw writes the session back to disk at end of turn, overwriting any truncation.

**Stop after any exec(delegate) result**
BOOT.md/AGENTS.md say to stop immediately after exec(delegate) returns — regardless of whether it returned SENT or an error. Without this, Gemini ran a second model turn on failure, causing a "typing..." indicator after rate limit errors (OC-012). Mode 1 exec calls (/quota, /gemini_requests) are explicitly excluded from this stop rule.

**`allowBundled: ["__none__"]` (not `[]`)**
Empty allowlist means "allow all" in openclaw's logic. A non-empty list with no matching names disables all 55 bundled skills. Workspace skills are always allowed regardless.

**`--continue` on delegate, and per-project sub-sessions**
openclaw_claude accumulates session history for diagnostics and openclaw knowledge. Project work gets isolated `--continue` sessions in their own dirs — each project's Claude has full conversation history without cross-project contamination.

**`projects/CLAUDE.md` as recursion guard**
Sub-sessions spawned in `projects/<slug>/` walk up to `projects/CLAUDE.md` before reaching `/home/pranav/CLAUDE.md`. This file says "you're in a project, just do the work" — preventing a sub-session from trying to spawn further sub-sessions.

**Lock file on delegate**
Gemini sometimes double-fires execs. The `mkdir` lock (atomic) ensures only one Claude invocation runs at a time; second caller gets SENT immediately.

**Skill description embeds the exec command**
Gemini was hallucinating wrong SKILL.md paths (ENOENT). Embedding the command in the frontmatter `description` means Gemini never needs to read the file.

**`SKIP_GATEWAY_RESTART=1`**
`run-tests` restarts the gateway as part of Test 4. When triggered from Discord, that kills the session mid-run. This env var skips the restart when running inside the gateway.

**Git integration scoped to openclaw-config only**
Project repos (standingTableController, etc.) are not tracked — they're code, not infrastructure. openclaw-config tracks only the routing/config layer. Separate concerns.

**`send-gemini-stats` via system crontab (not openclaw cron)**
The gemini-stats openclaw cron used Gemini to exec `send-gemini-stats`. When Gemini is rate-limited, the cron itself fails. Since the script doesn't need AI, it's now a native crontab entry — no Gemini dependency.

---

## Known Risks

### OC-001 — retry.attempts=1 not applying (wontfix)
`channels.discord.retry.attempts=1` in openclaw.json has no effect on the embedded agent model retry loop. Root cause: `@google/genai` SDK `DEFAULT_RETRY_ATTEMPTS=5`, not configurable via openclaw config. **Partial mitigation:** SDK patched directly (`DEFAULT_RETRY_ATTEMPTS=1` in node_modules). Note: patch is lost on `openclaw update`.

### OC-002 — RPM exhaustion sends error to Discord (MEDIUM)
When all models hit rate limits, openclaw sends an "API rate limit" error message to Discord (no `-# sent by claude` watermark). Message is not silently dropped but the error UX is poor.
**Workaround:** avoid heavy integration test runs during active use hours.

### `--continue` session context growth (MEDIUM)
openclaw_claude accumulates session history across all Discord conversations. Over weeks/months the context window fills up.
**Mitigation:** openclaw compaction mode set to "safeguard".

### Delegate lock drops parallel requests (LOW-MEDIUM)
If two Discord messages arrive simultaneously, the second is silently dropped (returns SENT without delegating). Intentional for duplicate prevention, but legitimate parallel requests lose the second message.

### Concurrent `agent --continue` on same project (LOW)
If two messages reference the same project simultaneously, both sub-sessions could write to the same JSONL session file — corrupted history. Protected at the Gemini→delegate level by the lock, but not at the sub-session level.

### Prompt injection via message content (MEDIUM)
User message is passed verbatim into Claude's prompt. A crafted message could attempt to override instructions. No filtering layer — LLM-level injection is possible.

### Gateway restart kills active sessions (LOW — mitigated)
`systemctl --user restart openclaw-gateway` SIGTERMs any active delegate call.
**Mitigation:** `SKIP_GATEWAY_RESTART=1` in run-tests. Manual restarts still a risk.

### AGENTS.md / BOOT.md drift (LOW)
Both files define routing rules independently. If one is updated without the other, Gemini reads inconsistent instructions. Auto-commit via path watcher captures both, but content sync is manual discipline.
