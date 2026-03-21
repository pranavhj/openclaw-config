# openclaw System Architecture
_Last updated: 2026-03-20_

---

## Message Flow (End-to-End)

```
┌─────────────────────────────────────────────────────────────────┐
│                     INBOUND CHANNELS                            │
│                                                                 │
│   Discord DM ──────────────────┐                               │
│   (allowFrom: 1277144623231537274)                             │
│                                │                               │
│   WhatsApp ─────────────────── ┤──► openclaw gateway          │
│   (allowFrom: +12403967835)    │    port 18789                 │
│                                │                               │
│   openclaw CLI ────────────────┘                               │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                      GEMINI (agent:main)                        │
│                                                                 │
│  Model: google/gemini-2.5-flash                                │
│  Fallbacks: gemini-2.0-flash-lite → groq/llama-3.3-70b        │
│  Workspace: /home/pranav/.openclaw/workspace/                   │
│  Skills: 5 workspace only (55 bundled disabled via             │
│          allowBundled: ["__none__"])                            │
│                                                                 │
│  Reads on startup:                                              │
│    BOOT.md     → routing rules (Mode 1/2)                      │
│    AGENTS.md   → routing rules, group chat etiquette           │
│    (session cleared before each turn — stateless router)        │
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
│  └─────────────────────────────────────────────────┘           │
│                                                                 │
│  Every response ends with:                                      │
│    python3 /home/pranav/gemini_counter.py  (quota footer)      │
└─────────────────────────────────────────────────────────────────┘
                    │ Mode 2
                    │ exec(command: 'delegate ...')
                    ▼
┌─────────────────────────────────────────────────────────────────┐
│              /home/pranav/.local/bin/delegate                   │
│                                                                 │
│  1. Clear Gemini session JSONL (stateless router, no history)  │
│  2. Acquire lock: /tmp/openclaw/delegate.lock (mkdir atomic)   │
│     └─ If locked → echo SENT, exit (prevents duplicate runs)   │
│  3. Collect context:                                            │
│     • Projects list: ls /home/pranav/projects/                 │
│     • Conv log: tail -30 /tmp/openclaw/openclaw-YYYY-MM-DD.log │
│  4. Build prompt in temp file (handles special chars safely)    │
│  5. Run Claude:                                                 │
│     cd /home/pranav/projects/openclaw                          │
│     agent --continue --permission-mode bypassPermissions        │
│            --print "$(cat $PROMPT_FILE)"                        │
│  6. Log result to /tmp/openclaw/delegate-YYYY-MM-DD.log        │
│  7. Echo output (openclaw sees "SENT")                         │
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
│    ## Recent conversation (last 30 log lines)                   │
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
│   WhatsApp ─────── channel=whatsapp, target=+12403967835        │
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
│  │  OC-001 (open)   retry.attempts=1 not applying           │   │
│  │  OC-002 (open)   silent drop on full RPM exhaustion      │   │
│  │  OC-003 (fixed)  allowBundled:[] does nothing            │   │
│  │  OC-004 (fixed)  Gemini session not cleared between turns│   │
│  │  OC-005 (fixed)  55 bundled skills inflating tokens      │   │
│  │  OC-006 (fixed)  AGENTS.md was 9.3KB                     │   │
│  │  OC-007 (fixed)  route-audit used wrong working dir      │   │
│  │  OC-008 (fixed)  no per-project session isolation        │   │
│  │  OC-009 (fixed)  standingTable dropped (quota exhaustion)│   │
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
│   • API keys (Gemini, Groq, Ollama)
│   • Agent model: gemini-2.5-flash
│   • Fallbacks: gemini-2.0-flash-lite, groq/llama-3.3-70b
│   • Workspace: /home/pranav/.openclaw/workspace/
│   • skills.allowBundled: ["__none__"]  ← disables all 55 bundled skills
│   • Channels: discord (retry=1), whatsapp
│   • allowFrom: user IDs/phone numbers (allowlist)
│   • Gateway port: 18789, auth token
│   • Tools: coding profile, web search, exec security=full
│
├── BOOT.md                          ← GEMINI ROUTING RULES (boot-time)
│   • Mode 1: what Gemini handles itself
│   • Mode 2: delegate via delegate skill
│   • Quota footer: mandatory python3 gemini_counter.py
│
├── workspace/
│   ├── AGENTS.md                    ← GEMINI WORKSPACE INSTRUCTIONS (~1.3KB)
│   │   • Mode 1/2 routing (trimmed 86% from 9.3KB)
│   │   • Channel/target defaults (Discord DM ID, WhatsApp number)
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
            └── *.jsonl              ← cleared before each delegate turn

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
    │   • Clears Gemini session JSONL (stateless router)
    │   • Lock, logging, context gathering
    │   • Invokes: cd projects/openclaw && agent --continue
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
```

---

## Agent Responsibilities

| Agent | Model | Working Dir | Config | Responsibility |
|---|---|---|---|---|
| **Gemini** (agent:main) | gemini-2.5-flash | `.openclaw/workspace/` | BOOT.md + AGENTS.md | Stateless router: classify → load skill → exec delegate or exec-dispatch → quota footer. Session cleared before each turn. |
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
| Gemini session history | growing | 0 (cleared each turn) |
| **Total estimate** | **~3,934/req** | **~1,200–1,500/req** |

Result: ~60–65% reduction. Daily message capacity ~263 → ~650+ at 1M TPD limit.

---

## Key Design Decisions & Why

**`yieldMs: 120000` on delegate exec**
Default is 10s which backgrounds the command before Claude responds. 2 min gives Claude time to complete.

**Session cleared before each delegate turn**
Gemini is a pure router — it needs zero cross-turn context. Clearing the JSONL keeps each routing decision stateless and eliminates accumulated token overhead.

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

---

## Known Risks

### OC-001 — retry.attempts=1 not applying (HIGH)
`channels.discord.retry.attempts=1` in openclaw.json has no effect on the embedded agent model retry loop, which still retries each model 4×. On rate limit: 3 models × 4 retries = 12 wasted API calls, burning RPM budget and amplifying OC-002.

### OC-002 — Silent message drop on full RPM exhaustion (HIGH)
When all models in the fallback chain hit per-minute rate limits simultaneously, the message is silently dropped — no Discord notification, no retry queue. User has no way to know it happened.
**Workaround:** wait 2+ minutes after integration test runs before sending real messages.

### Groq fallback can't delegate (HIGH)
When groq takes over, exec tool is not provisioned. It either responds with text or errors "exec not in request.tools". Message is lost either way.

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
