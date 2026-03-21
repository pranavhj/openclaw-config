#!/bin/bash
# Pull live configs into the repo. Run this before committing changes made directly on the machine.
REPO="$(cd "$(dirname "$0")/.." && pwd)"

cp /home/pranav/.openclaw/BOOT.md                                        "$REPO/config/BOOT.md"
cp /home/pranav/.openclaw/workspace/AGENTS.md                            "$REPO/workspace/AGENTS.md"
cp /home/pranav/.openclaw/workspace/skills/delegate/SKILL.md             "$REPO/workspace/skills/delegate/SKILL.md"
cp /home/pranav/.openclaw/workspace/skills/discord-send/SKILL.md         "$REPO/workspace/skills/discord-send/SKILL.md"
cp /home/pranav/.openclaw/workspace/skills/quota/SKILL.md                "$REPO/workspace/skills/quota/SKILL.md"
cp /home/pranav/.openclaw/workspace/skills/gemini-requests/SKILL.md      "$REPO/workspace/skills/gemini-requests/SKILL.md"
cp /home/pranav/.openclaw/workspace/skills/routing-audit/SKILL.md        "$REPO/workspace/skills/routing-audit/SKILL.md"
cp /home/pranav/projects/openclaw/CLAUDE.md                              "$REPO/agents/openclaw-CLAUDE.md"
cp /home/pranav/projects/CLAUDE.md                                       "$REPO/agents/projects-CLAUDE.md"
cp /home/pranav/.local/bin/delegate                                      "$REPO/bin/delegate"
cp /home/pranav/.local/bin/route-audit                                   "$REPO/bin/route-audit"
cp /home/pranav/.local/bin/run-tests                                     "$REPO/bin/run-tests" 2>/dev/null || true

echo "Synced live configs into $REPO"
echo "Review changes with: git -C $REPO diff"
