#!/usr/bin/env python3
"""
rc_commands.py — parse and format the Discord `rc` command (OC-041). Pure functions,
no Discord or CLI calls, so they are unit-testable. discord-bot.py does the I/O.

Commands:
    rc | rc help                 usage
    rc list                      live Remote Control sessions + links
    rc create <name>             new project folder (asks which root), then start RC
    rc <project>                 list conversations to resume (or start fresh if none)
    rc <project> <n>             resume conversation n from that list
    rc <project> new             fresh conversation
    rc stop <project>            stop Remote Control background sessions there
    rc restore                   bring back bot-started sessions (after reboot)
    <n> | copy | takeover        answer a pending question (10 min window)

Anything else starting with "rc " that does not name a project falls through to normal
routing, so messages like "rc car won't charge" are not hijacked.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path

PENDING_TTL_S = 600
FOOTER = '-# sent by claude'
NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')
RESERVED = {'list', 'stop', 'restore', 'new', 'create', 'help'}
YES_RE = re.compile(r'^(y|yes|yeah|yep|yup|sure|ok|okay|do it|go ahead|take ?over|take it over)\b[\s.!]*'
                    r'(do it|go ahead|it|please|pls|now)?[\s.!]*$')

USAGE = (
    '**Remote Control**\n'
    '`rc <project>` — pick a conversation to resume\n'
    '`rc <project> new` — fresh conversation\n'
    '`rc create <name>` — new project folder (I’ll ask where)\n'
    '`rc list` · `rc stop <project>` · `rc restore`\n'
    'Prefix a message with `!` to send it through the Discord pipeline even when the '
    'project has a live Remote Control session.\n' + FOOTER
)


def parse(content: str, known_projects: dict, pending: dict | None = None) -> dict | None:
    """Return an action dict, or None if this message is not an rc command."""
    s = content.strip()
    low = s.lower()
    if pending and pending.get('expires', 0) > time.time():
        if re.fullmatch(r'[0-9]{1,2}', s) and pending.get('kind') in ('convo', 'create'):
            return {'action': 'pick', 'n': int(s)}
        if pending.get('kind') == 'elsewhere':
            if low in ('copy', 'takeover'):
                return {'action': low}
            if YES_RE.match(low):  # the bot's question names takeover as the "yes" answer
                return {'action': 'takeover'}
    parts = s.split()
    if not parts or parts[0].lower() != 'rc':
        return None
    if len(parts) == 1 or (len(parts) == 2 and parts[1].lower() == 'help'):
        return {'action': 'help'}
    sub = parts[1].lower()
    if len(parts) == 2 and sub in ('list', 'restore'):
        return {'action': sub}
    if len(parts) in (3, 4) and sub in ('create', 'new'):
        name = parts[2]
        if not NAME_RE.match(name) or name.isdigit() or name.lower() in RESERVED:
            return {'action': 'bad_name', 'name': name}
        if len(parts) == 4:  # rc create <name> <root#>: one step, no question needed
            if not re.fullmatch(r'[0-9]{1,2}', parts[3]):
                return None
            return {'action': 'create', 'name': name, 'root': int(parts[3])}
        return {'action': 'create', 'name': name}
    if len(parts) == 3 and sub == 'stop':
        return {'action': 'stop', **_match(parts[2], known_projects)}
    if len(parts) in (2, 3):
        arg = parts[2].lower() if len(parts) == 3 else None
        if arg is not None and arg != 'new' and not re.fullmatch(r'[0-9]{1,2}', arg):
            return None
        m = _match(parts[1], known_projects)
        if m['project'] is None and not m['candidates']:
            return None  # e.g. "rc car" — not ours, route normally
        return {'action': 'open', 'arg': arg, **m}
    return None


def _match(name: str, known_projects: dict) -> dict:
    key = name.lower()
    if key in known_projects:
        return {'project': key, 'path': known_projects[key], 'candidates': [], 'name': name}
    cands = sorted(n for n in known_projects if key in n)[:10] if len(key) >= 3 else []
    return {'project': None, 'path': None, 'candidates': cands, 'name': name}


def new_pending(kind: str, **data) -> dict:
    return {'kind': kind, 'expires': time.time() + PENDING_TTL_S, **data}


# Actions an LLM-submitted request may not trigger: they need the user's own reply.
ROUTER_FORBIDDEN = {'takeover', 'copy', 'pick'}


def pending_context(pending: dict | None) -> str:
    """Plain-text description of the bot's open question, injected into the router prompt
    so a natural-language answer ("the login one") can be turned into a full rc command."""
    if not pending or pending.get('expires', 0) <= time.time():
        return ''
    kind = pending.get('kind')
    if kind == 'convo':
        lines = [f'The bot listed conversations for project `{pending.get("project")}` and asked '
                 f'which one to resume. Options:']
        lines += [f'  {i}. {label}' for i, label in enumerate(pending.get('labels', []), 1)]
        lines.append('  0. new conversation')
        lines.append(f'Answer with: rc {pending.get("project")} <number>   (or rc {pending.get("project")} new)')
        return '\n'.join(lines)
    if kind == 'create':
        lines = [f'The bot asked where to create new project `{pending.get("name")}`. Options:']
        lines += [f'  {i}. {r}' for i, r in enumerate(pending.get('roots', []), 1)]
        lines.append(f'Answer with: rc create {pending.get("name")} <number>')
        return '\n'.join(lines)
    if kind == 'candidates':
        return (f'The bot could not find project `{pending.get("name")}` and offered: '
                + ', '.join(pending.get('candidates', []))
                + '. Answer with the full command using the right name, e.g. rc <project>.')
    if kind == 'elsewhere':
        return ('The bot asked whether to take over a conversation that is open in a terminal. '
                'Only the user can answer that (by replying yes/takeover/copy). Do NOT submit '
                'takeover or copy; if the user seems to agree, tell them to reply "yes".')
    return ''


def format_candidates(name: str, cands: list[str]) -> str:
    if not cands:
        return f'No project called `{name}`.\n{FOOTER}'
    return (f'No exact project `{name}`. Did you mean: ' + ', '.join(f'`{c}`' for c in cands)
            + f'?\n{FOOTER}')


def format_roots(name: str, roots: list[str]) -> str:
    lines = [f'Where should I create `{name}`?']
    lines += [f'**{i}.** `{r}`' for i, r in enumerate(roots, 1)]
    lines.append(f'Reply with a number.\n{FOOTER}')
    return '\n'.join(lines)


_SOURCE_ICON = {'terminal': '\U0001f5a5', 'discord': '\U0001f4ac', 'unknown': '❔'}


def format_conversations(project: str, convos: list[dict], live_rc: set[str],
                         live_other: set[str]) -> str:
    lines = [f'Conversations in `{project}` (newest first):']
    for i, c in enumerate(convos, 1):
        when = datetime.fromtimestamp(c['mtime']).strftime('%b %d %H:%M')
        label = c['title'] or c['first_prompt'][:70] or '(untitled)'
        state = ''
        if c['session_id'] in live_rc:
            state = ' · \U0001f7e2 live on RC'
        elif c['session_id'] in live_other:
            state = ' · \U0001f512 open in a terminal'
        lines.append(f'**{i}.** {_SOURCE_ICON.get(c["source"], "")} {when} · {label} '
                     f'· {c["user_turns"]} msgs{state}')
    lines.append('**0.** ➕ new conversation')
    lines.append(f'Reply with a number. \U0001f5a5 terminal · \U0001f4ac Discord\n{FOOTER}')
    return '\n'.join(lines)


def format_ready(res: dict) -> str:
    if res.get('reused'):
        head = f'\U0001f7e2 `{res["name"]}` is already live on Remote Control'
    elif res.get('copied'):
        head = (f'✅ `{res["name"]}` is live on Remote Control (as a copy — the original '
                f'session had no Remote Control)')
    else:
        head = f'✅ `{res["name"]}` is live on Remote Control'
    return (f'{head}\n{res["url"]}\n-# job `{res["job_id"]}` · permissions: bypass '
            f'· sent by claude')


def format_live_elsewhere(project: str, status: str | None) -> str:
    idle = status == 'idle'
    lines = [f'🔒 That conversation in `{project}` is open in a terminal without Remote '
             f'Control (status: `{status}`). Reply:']
    if idle:
        lines.append('• `yes` (or `takeover`) — close the Claude in that terminal and continue the '
                     'same conversation on Remote Control (history kept)')
    else:
        lines.append('• `takeover` — only works once it is idle; it is busy now')
    lines.append('• `copy` — start a copy on Remote Control (it will diverge from the terminal)')
    lines.append(f'Or type `/remote-control` in that terminal when you’re at the PC.\n{FOOTER}')
    return '\n'.join(lines)


def format_list(live: list[dict], dormant: list[dict]) -> str:
    if not live and not dormant:
        return f'No Remote Control sessions. Start one with `rc <project>`.\n{FOOTER}'
    lines = []
    if live:
        lines.append('**Live on Remote Control:**')
        for r in live:
            kind = 'bg' if r.get('jobId') else 'terminal'
            lines.append(f'• `{r.get("name")}` · {Path(r.get("cwd", "")).name} · {kind}\n'
                         f'  {r["url"]}')
    if dormant:
        lines.append('**Not running** (bring back with `rc restore`):')
        lines += [f'• `{d.get("name")}` · {Path(d.get("cwd", "")).name}' for d in dormant]
    lines.append(FOOTER)
    return '\n'.join(lines)


def format_restore(results: list[dict]) -> str:
    if not results:
        return f'Nothing to restore — every bot-started session is already live.\n{FOOTER}'
    lines = ['**Restore:**']
    for r in results:
        if r['ok']:
            lines.append(f'✅ `{r["name"]}` {r["url"]}')
        else:
            lines.append(f'❌ `{r["name"]}`: {r["error"][:200]}')
    lines.append(FOOTER)
    return '\n'.join(lines)


def format_guard(project: str, url: str) -> str:
    return (f'\U0001f7e2 `{project}` has a live Remote Control session — continue there:\n{url}\n'
            f'-# Not sent via Discord to avoid two writers on one conversation. Prefix with `!` '
            f'to send anyway, or `rc stop {project}`. · sent by claude')
