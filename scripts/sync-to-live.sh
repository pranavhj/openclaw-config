#!/bin/bash
# Deploy repo configs to live paths. Run after pulling from GitHub to apply changes.
# WARNING: Does NOT restart the gateway — run: systemctl --user restart openclaw-gateway
REPO="$(cd "$(dirname "$0")/.." && pwd)"

cp "$REPO/config/BOOT.md"                                        /home/pranav/.openclaw/BOOT.md
cp "$REPO/workspace/AGENTS.md"                                   /home/pranav/.openclaw/workspace/AGENTS.md
cp "$REPO/workspace/skills/delegate/SKILL.md"                    /home/pranav/.openclaw/workspace/skills/delegate/SKILL.md
cp "$REPO/workspace/skills/discord-send/SKILL.md"                /home/pranav/.openclaw/workspace/skills/discord-send/SKILL.md
cp "$REPO/workspace/skills/quota/SKILL.md"                       /home/pranav/.openclaw/workspace/skills/quota/SKILL.md
cp "$REPO/workspace/skills/gemini-requests/SKILL.md"             /home/pranav/.openclaw/workspace/skills/gemini-requests/SKILL.md
cp "$REPO/workspace/skills/routing-audit/SKILL.md"               /home/pranav/.openclaw/workspace/skills/routing-audit/SKILL.md
cp "$REPO/agents/openclaw-CLAUDE.md"                             /home/pranav/projects/openclaw/CLAUDE.md
cp "$REPO/agents/projects-CLAUDE.md"                             /home/pranav/projects/CLAUDE.md
cp "$REPO/bin/delegate"                                          /home/pranav/.local/bin/delegate
cp "$REPO/bin/route-audit"                                       /home/pranav/.local/bin/route-audit
[ -f "$REPO/bin/run-tests" ] && cp "$REPO/bin/run-tests"         /home/pranav/.local/bin/run-tests

chmod +x /home/pranav/.local/bin/delegate /home/pranav/.local/bin/route-audit /home/pranav/.local/bin/run-tests 2>/dev/null

echo "Deployed configs from $REPO to live paths"
echo "Restart gateway: systemctl --user restart openclaw-gateway"
