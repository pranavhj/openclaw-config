# OpenClaw Issue Tracker

Format: `OC-NNN | type | status | title`
Types: `bug` `feature` `config`
Statuses: `open` `fixed` `wontfix` `investigating`

| ID | Type | Status | Title | Commit |
|----|------|--------|-------|--------|
| [OC-001](issues/OC-001-retry-attempts-not-applying.md) | bug | wontfix | `retry.attempts=1` not applied to embedded agent — 4× retry hardcoded in `@google/genai` SDK, not configurable | — |
| [OC-002](issues/OC-002-rpm-exhaustion-drops-messages.md) | bug | open | RPM exhaustion: all fallbacks 429, gateway sends error but user must resend manually | — |
| [OC-003](issues/OC-003-allowbundled-empty-ineffective.md) | bug | fixed | `allowBundled: []` does not disable bundled skills (empty = allow all) | `init` |
| [OC-004](issues/OC-004-session-not-cleared-before-delegate.md) | feature | fixed | Gemini accumulates cross-turn context as router (add session clear) | `init` |
| [OC-005](issues/OC-005-bundled-skills-token-overhead.md) | feature | fixed | 55 bundled skills inflate every Gemini prompt by ~2500 tokens | `init` |
| [OC-006](issues/OC-006-agents-md-too-large.md) | feature | fixed | AGENTS.md was 9.3KB, trimmed to ~1.3KB (86% reduction) | `init` |
| [OC-007](issues/OC-007-route-audit-wrong-workdir.md) | bug | fixed | route-audit ran `agent` from wrong directory (used `~` not `projects/openclaw`) | `init` |
| [OC-008](issues/OC-008-per-project-session-isolation.md) | feature | fixed | All projects shared one Claude session — no isolation between projects | `init` |
| [OC-009](issues/OC-009-standingTable-dropped-quota.md) | bug | fixed | standingTableController message silently dropped (quota exhaustion at 17:54 PDT) | `init` |
| [OC-010](issues/OC-010-gemini-channel-misidentification.md) | bug | fixed | Gemini routed Discord message to WhatsApp (BOOT.md out of date, ambiguous channel rules) | `fix(OC-010)` |
| [OC-011](issues/OC-011-gemini-second-turn-after-delegate.md) | bug | fixed | Gemini did second model turn after delegate (quota footer) — caused gateway error on Discord | `fix(OC-011)` |
| [OC-012](issues/OC-012-gemini-second-turn-after-exec-error.md) | bug | fixed | Gemini did second model turn after exec(delegate) returned error — typing indicator after rate limit error | `fix(OC-012)` |
| [OC-013](issues/OC-013-quota-footer-typing-after-response.md) | bug | fixed | Quota footer exec kept typing indicator alive 5–10s after Claude already responded | — |
| [OC-014](issues/OC-014-gemini-delegates-own-text-not-user-message.md) | bug | fixed | Gemini composed its own text and delegated that instead of the original user message verbatim | — |
| [OC-015](issues/OC-015-delegate-exec-failed-on-apostrophes.md) | bug | fixed | Delegate exec fails when message contains apostrophe — Gemini wraps in single quotes, shell parse error | `fix(OC-015)` |
| [OC-016](issues/OC-016-newlines-break-delegate-exec.md) | bug | fixed | Newlines in user messages break delegate exec (bash exit 127) — message silently dropped | `fix(OC-016)` |
| [OC-017](issues/OC-017-gemini-overwrote-agents-md.md) | bug | fixed | Gemini used write tool to overwrite AGENTS.md with anti-delegation instructions | `fix(OC-017)` |
| [OC-018](issues/OC-018-claude-created-rogue-gemini-skill.md) | bug | fixed | Claude created rogue Alexa skill in Gemini workspace + alexa-send binary in ~/.local/bin | `fix(OC-018)` |
