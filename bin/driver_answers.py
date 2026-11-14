"""Answers to plan-driver owner questions from Discord (OC-049; plan-driver DESIGN §11b).

A plan-driver question carries an id like `Q-7K2M` (always with the hyphen) and numbered options. The owner answers:
    Q-7K2M 1
    q-7k2m use the second one, but keep the old column
    Q-7K2M 1  Q-9PXA 2            (several on one line: each id starts a new answer)
A message is taken as answers only when it starts with an id and at least one of its ids is a known question (the
index below); anything else ("Query: ...", "Queue the check", a bare "2") goes to the router as usual. A bare number
is never an answer: it could belong to any question.

The id's project comes from plan-driver's index (`~/.claude/state/plan-driver-questions.json`, or
$PLAN_DRIVER_QUESTIONS_INDEX): the project root, and the python + package path of the driver that asked. Each answer
runs `python -m plan_driver answer --root <root> <id> <answer> --by discord` there, which takes the first answer from
any channel (Claude, the orchestrator, this) and refuses the rest. Deterministic: no Claude call.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

CHANNEL_ID = "1564021528419508386"     # #reminders, where the driver posts its questions
_ID = re.compile(r"(?<![\w-])Q-([2-9A-HJ-NP-Z]{4})(?![\w-])", re.IGNORECASE)   # the hyphen is required: "Query" is chat
TIMEOUT_S = 60
MAX_PARTS = 10


def parse(content: str) -> list[tuple[str, str]]:
    """[(id, answer)] when the message starts with an id, one pair per id (an id starts the next answer, whatever
    separates them); [] when it does not start with an id or any id has no answer text."""
    text = (content or "").strip()
    ids = list(_ID.finditer(text))
    if not ids or ids[0].start() != 0:
        return []
    out = []
    for k, m in enumerate(ids):
        end = ids[k + 1].start() if k + 1 < len(ids) else len(text)
        seg = text[m.end():end].strip()
        reply = seg.splitlines()[0].strip() if seg else ""      # one line per answer; other lines are not answers
        reply = re.sub(r"^[:.)]\s*", "", reply)                 # "Q-7K2M: 1", "Q-7K2M) 1"
        reply = re.sub(r"[\s,;]+$", "", reply)                  # the separator before the next id
        reply = re.sub(r"\s+(and|&)$", "", reply, flags=re.IGNORECASE)
        if not reply:
            return []
        out.append((f"Q-{m.group(1).upper()}", reply))
    return out[:MAX_PARTS]


def index_path() -> Path:
    return Path(os.environ.get("PLAN_DRIVER_QUESTIONS_INDEX") or "~/.claude/state/plan-driver-questions.json").expanduser()


def _index() -> dict:
    try:
        data = json.loads(index_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def lookup(qid: str, index: dict | None = None) -> dict | None:
    hit = (index if index is not None else _index()).get(qid)
    return hit if isinstance(hit, dict) and hit.get("root") else None


def answer_one(qid: str, reply: str, run=subprocess.run, index: dict | None = None) -> str:
    """One line for the reply message."""
    hit = lookup(qid, index)
    if hit is None:
        return f"❌ {qid}: unknown question id (not asked on this PC, or a typo)"
    py = hit.get("python") or "python"
    path = os.pathsep.join(p for p in (hit.get("pythonpath", ""), os.environ.get("PYTHONPATH", "")) if p)
    env = {**os.environ, "PYTHONPATH": path, "PYTHONIOENCODING": "utf-8"}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    # A leading space: argparse would read "@file" as an arguments file and "-x" as an option; plan-driver strips it.
    argv = [py, "-m", "plan_driver", "answer", "--root", hit["root"], "--by", "discord", qid, " " + reply]
    try:
        proc = run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_S,
                   cwd=hit.get("pythonpath") or None, env=env, creationflags=flags)
    except subprocess.TimeoutExpired:
        return (f"⚠️ {qid}: the answer command took over {TIMEOUT_S} s; it may or may not have been recorded "
                f"(check: python -m plan_driver questions --root {hit['root']})")
    except (OSError, subprocess.SubprocessError) as e:
        return f"❌ {qid}: not recorded, the answer command did not run ({type(e).__name__})"
    out = (proc.stdout.strip() or proc.stderr.strip()).splitlines()
    text = out[-1] if out else f"exit {proc.returncode}"
    if proc.returncode == 0:
        return f"✅ {text}"
    if proc.returncode == 3:
        return f"ℹ️ {text}"
    return f"❌ {qid}: {text}"


def answer_all(content: str, run=subprocess.run) -> str | None:
    """The reply text, or None when the message is not answers (it then goes to the router)."""
    pairs = parse(content)
    if not pairs:
        return None
    index = _index()
    if not any(lookup(q, index) for q, _ in pairs):     # no known id: chat that happens to start like one
        return None
    lines = [answer_one(q, r, run, index) for q, r in pairs]
    extra = [ln.strip() for ln in content.splitlines() if ln.strip() and not _ID.search(ln)]
    if extra:
        lines.append(f"(not part of any answer, ignored: {' / '.join(extra)[:200]})")
    return "\n".join(lines)
