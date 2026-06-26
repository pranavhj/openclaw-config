#!/usr/bin/env python3
"""project_store.py — JSONL append/query + schema validation for gateway projects.

Storage format: one .jsonl file per data type under projects/<slug>/data/<type>.jsonl
Each line is a JSON object with the user's data plus _id and _ts metadata fields.
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECTS_ROOT = Path.home() / 'projects'
PROJECT_SUFFIX = '_llm_gateway'


def load_project(project_dir: Path) -> dict:
    """Load project.json from a project directory."""
    return json.loads((project_dir / 'project.json').read_text(encoding='utf-8'))


def validate_entry(project: dict, data_type: str, data: dict) -> str | None:
    """Validate data against project schema. Returns error string or None if valid."""
    schema = project.get('schema', {})
    if not schema:
        return None  # no schema = accept anything

    type_schema = schema.get(data_type)
    if type_schema is None:
        valid_types = list(schema.keys())
        return f'Unknown data type: {data_type}. Valid types: {valid_types}'

    # Basic required field check — fields with "(required)" in description
    if isinstance(type_schema, dict):
        for field, desc in type_schema.items():
            if isinstance(desc, str) and 'required' in desc.lower():
                if field not in data or data[field] is None or data[field] == '':
                    return f'Missing required field: {field}'

    return None


def append_entry(project_dir: Path, project: dict, data_type: str, data: dict) -> str:
    """Append a data entry to the project's JSONL store.

    Returns the entry ID.
    """
    # Validate
    error = validate_entry(project, data_type, data)
    if error:
        raise ValueError(error)

    # Generate ID
    entry_id = f'entry_{int(time.time() * 1000)}'

    # Build record with metadata
    record = {
        '_id': entry_id,
        '_ts': datetime.now(timezone.utc).isoformat(),
        '_type': data_type,
        **data,
    }

    # Ensure data directory exists
    data_dir = project_dir / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)

    # Append to type-specific JSONL file
    jsonl_path = data_dir / f'{data_type}.jsonl'
    with open(jsonl_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record) + '\n')

    return entry_id


def query_entries(
    project_dir: Path,
    data_type: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Query entries from project data store.

    Args:
        project_dir: Path to the project directory
        data_type: Filter by data type (None = all types)
        since: ISO8601 timestamp — only return entries after this time
        limit: Maximum number of entries to return
    """
    data_dir = project_dir / 'data'
    if not data_dir.exists():
        return []

    # Determine which files to read
    if data_type:
        files = [data_dir / f'{data_type}.jsonl']
    else:
        files = sorted(data_dir.glob('*.jsonl'))

    entries = []
    for jsonl_path in files:
        if not jsonl_path.exists():
            continue
        try:
            for line in jsonl_path.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    # Filter by timestamp
                    if since:
                        ts = entry.get('timestamp', entry.get('_ts', ''))
                        if ts < since:
                            continue
                    entries.append(entry)
                except json.JSONDecodeError:
                    continue
        except Exception:
            continue

    # Sort by timestamp descending (most recent first)
    entries.sort(
        key=lambda e: e.get('timestamp', e.get('_ts', '')),
        reverse=True,
    )

    return entries[:limit]
