#!/usr/bin/env python3
"""
project_list.py — Discover known projects across standard directories.

Importable module + standalone CLI:
    python project_list.py              # print JSON list
    python project_list.py --names      # print names only (one per line)
    python project_list.py --json       # print full {name: path} dict

As a module:
    from project_list import discover_projects
    projects = discover_projects()  # {lowercase_name: full_path}
"""

from pathlib import Path

# Filtered roots: only dirs with .claude/ or PROGRESS.md count as projects
FILTERED_ROOTS = [
    Path.home() / 'projects',
    Path.home() / 'AndroidStudioProjects',
    Path.home() / 'PycharmProjects',
    Path.home() / 'UnityProjects',
]

# Unfiltered roots: every subdir is a project
UNFILTERED_ROOTS = [
    Path('D:/MyData/Software'),
]

EXCLUDE_NAMES: set = {'watchlatercleaner', 'claude-test-nomod'}


def discover_projects() -> dict:
    """Return {lowercase_name: full_path} for known projects."""
    projects = {}
    for root in FILTERED_ROOTS:
        if not root.exists():
            continue
        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.name in EXCLUDE_NAMES:
                continue
            if (d / '.claude').exists() or (d / 'PROGRESS.md').exists():
                projects[d.name.lower()] = str(d)
    for root in UNFILTERED_ROOTS:
        if not root.exists():
            continue
        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.name in EXCLUDE_NAMES:
                continue
            projects[d.name.lower()] = str(d)
    return projects


if __name__ == '__main__':
    import json
    import sys

    projects = discover_projects()
    if '--names' in sys.argv:
        for name in sorted(projects):
            print(name)
    elif '--json' in sys.argv:
        print(json.dumps(projects, indent=2))
    else:
        print(json.dumps(sorted(projects.keys())))
