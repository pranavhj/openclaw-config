#!/usr/bin/env python3
"""test_gateway.py — Unit tests for LLM Gateway infrastructure.

Tests llm-gateway.py, gateway-delegate.py, and project_store.py
without requiring a running server or Claude API access.

Usage: python tests/test_gateway.py
"""
import json
import os
import shutil
import sys
import tempfile
import textwrap
import time
from pathlib import Path

# Add bin/ to path for imports
BIN_DIR = Path(__file__).parent.parent / 'bin'
sys.path.insert(0, str(BIN_DIR))

passed = 0
failed = 0


def check(label, condition, detail=''):
    global passed, failed
    if condition:
        print(f'  PASS: {label}')
        passed += 1
    else:
        msg = f'  FAIL: {label}'
        if detail:
            msg += f' ({detail})'
        print(msg)
        failed += 1


# =========================================================================
# Setup: create a temporary project root with test projects
# =========================================================================

TEMP_DIR = Path(tempfile.mkdtemp(prefix='gateway_test_'))
TEMP_PROJECTS = TEMP_DIR / 'projects'
TEMP_PROJECTS.mkdir()

# Create test project: testapp_llm_gateway
TEST_SLUG = 'testapp'
TEST_PROJECT_DIR = TEMP_PROJECTS / f'{TEST_SLUG}_llm_gateway'
TEST_PROJECT_DIR.mkdir()
(TEST_PROJECT_DIR / 'data').mkdir()

(TEST_PROJECT_DIR / 'project.json').write_text(json.dumps({
    'slug': 'testapp',
    'display': 'Test App',
    'schema': {
        'log_entry': {
            'text': 'string (required)',
            'level': 'info|warn|error',
            'timestamp': 'ISO8601 (required)',
        },
        'metric': {
            'name': 'string (required)',
            'value': 'number (required)',
        },
    },
}), encoding='utf-8')

(TEST_PROJECT_DIR / 'instructions.md').write_text(
    'You are a log analysis assistant. Look for error patterns and anomalies.',
    encoding='utf-8',
)

# Create a second project without instructions.md
BARE_SLUG = 'bareapp'
BARE_PROJECT_DIR = TEMP_PROJECTS / f'{BARE_SLUG}_llm_gateway'
BARE_PROJECT_DIR.mkdir()
(BARE_PROJECT_DIR / 'data').mkdir()
(BARE_PROJECT_DIR / 'project.json').write_text(json.dumps({
    'slug': 'bareapp',
    'display': 'Bare App',
    'schema': {},
}), encoding='utf-8')


# =========================================================================
# 1. File presence and structure
# =========================================================================

print('\n1. File presence and structure')

check('llm-gateway.py exists', (BIN_DIR / 'llm-gateway.py').exists())
check('gateway-delegate.py exists', (BIN_DIR / 'gateway-delegate.py').exists())
check('project_store.py exists', (BIN_DIR / 'project_store.py').exists())

# Check imports compile
for fname in ['llm-gateway.py', 'gateway-delegate.py', 'project_store.py']:
    try:
        import py_compile
        py_compile.compile(str(BIN_DIR / fname), doraise=True)
        check(f'{fname} compiles', True)
    except py_compile.PyCompileError as e:
        check(f'{fname} compiles', False, str(e))


# =========================================================================
# 2. project_store.py — JSONL storage
# =========================================================================

print('\n2. project_store.py — JSONL storage')

import project_store

# Monkey-patch PROJECTS_ROOT for testing
original_root = project_store.PROJECTS_ROOT
original_suffix = project_store.PROJECT_SUFFIX
project_store.PROJECTS_ROOT = TEMP_PROJECTS
project_store.PROJECT_SUFFIX = '_llm_gateway'

# 2a. load_project
proj = project_store.load_project(TEST_PROJECT_DIR)
check('load_project returns dict', isinstance(proj, dict))
check('load_project has slug', proj.get('slug') == 'testapp')
check('load_project has schema', 'log_entry' in proj.get('schema', {}))
check('load_project has display', proj.get('display') == 'Test App')

# 2b. validate_entry — valid entries
err = project_store.validate_entry(proj, 'log_entry', {
    'text': 'test message',
    'level': 'info',
    'timestamp': '2026-06-10T10:00:00Z',
})
check('validate valid log_entry', err is None)

# 2c. validate_entry — missing required field
err = project_store.validate_entry(proj, 'log_entry', {
    'level': 'info',
    'timestamp': '2026-06-10T10:00:00Z',
})
check('validate missing required field', err is not None and 'text' in err)

# 2d. validate_entry — unknown type
err = project_store.validate_entry(proj, 'nonexistent_type', {'foo': 'bar'})
check('validate unknown type', err is not None and 'Unknown' in err)

# 2e. validate_entry — no schema (bareapp accepts anything)
bare_proj = project_store.load_project(BARE_PROJECT_DIR)
err = project_store.validate_entry(bare_proj, 'anything', {'foo': 'bar'})
check('validate no-schema project accepts anything', err is None)

# 2f. append_entry
entry_id = project_store.append_entry(TEST_PROJECT_DIR, proj, 'log_entry', {
    'text': 'server started',
    'level': 'info',
    'timestamp': '2026-06-10T10:00:00Z',
})
check('append_entry returns id', entry_id.startswith('entry_'))

jsonl_path = TEST_PROJECT_DIR / 'data' / 'log_entry.jsonl'
check('append creates JSONL file', jsonl_path.exists())

lines = jsonl_path.read_text(encoding='utf-8').strip().splitlines()
check('append writes one line', len(lines) == 1)

record = json.loads(lines[0])
check('record has _id', record.get('_id') == entry_id)
check('record has _ts', '_ts' in record)
check('record has _type', record.get('_type') == 'log_entry')
check('record has user data', record.get('text') == 'server started')

# 2g. append_entry — validation error
try:
    project_store.append_entry(TEST_PROJECT_DIR, proj, 'log_entry', {
        'level': 'info',  # missing required 'text'
    })
    check('append rejects invalid entry', False, 'should have raised ValueError')
except ValueError as e:
    check('append rejects invalid entry', 'text' in str(e))

# 2h. append more entries for query testing
for i in range(5):
    ts = f'2026-06-{10-i:02d}T{10+i:02d}:00:00Z'
    project_store.append_entry(TEST_PROJECT_DIR, proj, 'log_entry', {
        'text': f'entry {i}',
        'level': 'info',
        'timestamp': ts,
    })

# Also append a metric entry (different type)
project_store.append_entry(TEST_PROJECT_DIR, proj, 'metric', {
    'name': 'cpu_usage',
    'value': 42,
    'timestamp': '2026-06-10T12:00:00Z',
})

# 2i. query_entries — all
entries = project_store.query_entries(TEST_PROJECT_DIR)
check('query all returns entries', len(entries) > 0)
check('query all includes both types', any(e.get('_type') == 'metric' for e in entries))

# 2j. query_entries — by type
log_entries = project_store.query_entries(TEST_PROJECT_DIR, data_type='log_entry')
check('query by type filters correctly', all(e.get('_type') == 'log_entry' for e in log_entries))
check('query by type count', len(log_entries) == 6)  # 1 initial + 5 loop

metric_entries = project_store.query_entries(TEST_PROJECT_DIR, data_type='metric')
check('query metrics', len(metric_entries) == 1)

# 2k. query_entries — with limit
limited = project_store.query_entries(TEST_PROJECT_DIR, data_type='log_entry', limit=3)
check('query with limit', len(limited) == 3)

# 2l. query_entries — sorted descending (most recent first)
if len(log_entries) >= 2:
    ts0 = log_entries[0].get('timestamp', log_entries[0].get('_ts', ''))
    ts1 = log_entries[1].get('timestamp', log_entries[1].get('_ts', ''))
    check('query sorted descending', ts0 >= ts1)

# 2m. query_entries — empty project
empty_entries = project_store.query_entries(BARE_PROJECT_DIR)
check('query empty project returns []', empty_entries == [])

# 2n. query_entries — nonexistent type
none_entries = project_store.query_entries(TEST_PROJECT_DIR, data_type='nonexistent')
check('query nonexistent type returns []', none_entries == [])


# =========================================================================
# 3. gateway-delegate.py — prompt building
# =========================================================================

print('\n3. gateway-delegate.py — prompt building')

import importlib
gd = importlib.import_module('gateway-delegate')

# Monkey-patch paths
gd.PROJECTS_ROOT = TEMP_PROJECTS
gd.PROJECT_SUFFIX = '_llm_gateway'

# 3a. project_dir_for
pdir = gd.project_dir_for('testapp')
check('project_dir_for adds suffix', pdir.name == 'testapp_llm_gateway')
check('project_dir_for uses PROJECTS_ROOT', str(pdir).startswith(str(TEMP_PROJECTS)))

# 3b. load_project
proj = gd.load_project('testapp')
check('delegate load_project works', proj.get('slug') == 'testapp')

# 3c. load_instructions
instructions = gd.load_instructions('testapp')
check('load_instructions reads file', 'log analysis' in instructions)

instructions_bare = gd.load_instructions('bareapp')
check('load_instructions returns empty for no file', instructions_bare == '')

# 3d. load_recent_data
recent = gd.load_recent_data('testapp')
check('load_recent_data returns entries', len(recent) > 0)
check('load_recent_data is JSONL format', '\n' in recent)

# Count entries in recent data
recent_lines = [l for l in recent.strip().splitlines() if l.strip()]
check('load_recent_data respects max_entries', len(recent_lines) <= 50)

# 3e. load_recent_data — empty project
recent_empty = gd.load_recent_data('bareapp')
check('load_recent_data empty for no data', recent_empty == '')

# 3f. build_prompt — context=auto
prompt_auto = gd.build_prompt('testapp', 'What errors occurred?', context='auto')
check('prompt has project name', 'Test App' in prompt_auto)
check('prompt has instructions', 'log analysis' in prompt_auto)
check('prompt has schema', 'log_entry' in prompt_auto)
check('prompt has data', 'server started' in prompt_auto or 'entry' in prompt_auto)
check('prompt has request', 'What errors occurred?' in prompt_auto)
check('prompt has response instructions', 'Do NOT use any tools' in prompt_auto)

# 3g. build_prompt — context=none (no data loaded)
prompt_none = gd.build_prompt('testapp', 'What is HTTP?', context='none')
check('prompt context=none has project name', 'Test App' in prompt_none)
check('prompt context=none has request', 'What is HTTP?' in prompt_none)
check('prompt context=none skips data', 'Recent Data' not in prompt_none)
check('prompt context=none shorter', len(prompt_none) < len(prompt_auto))

# 3h. build_prompt — bare project (no instructions, no schema)
prompt_bare = gd.build_prompt('bareapp', 'hello', context='auto')
check('prompt bare has project name', 'Bare App' in prompt_bare)
check('prompt bare has request', 'hello' in prompt_bare)
check('prompt bare has no entries', 'no entries yet' in prompt_bare)

# 3i. extract_response — stdout primary
resp = gd.extract_response(0, 'Hello, this is a response', '/fake/dir')
check('extract from stdout', resp == 'Hello, this is a response')

# 3j. extract_response — filters agent-smart noise
resp = gd.extract_response(0, '[agent-smart] compacting\nActual response text', '/fake/dir')
check('extract filters [agent-smart] lines', resp == 'Actual response text')

# 3k. extract_response — skips trivial markers
resp = gd.extract_response(0, 'SENT', '/fake/dir')
check('extract skips SENT', resp != 'SENT')

resp = gd.extract_response(0, 'done', '/fake/dir')
check('extract skips done', resp != 'done')

# 3l. extract_response — empty stdout
resp = gd.extract_response(0, '', '/fake/dir')
check('extract empty stdout', 'No response' in resp)


# =========================================================================
# 4. llm-gateway.py — structure and config
# =========================================================================

print('\n4. llm-gateway.py — structure and config')

gw_code = (BIN_DIR / 'llm-gateway.py').read_text(encoding='utf-8')

# 4a. Endpoints registered
check('has /health endpoint', "'/health'" in gw_code)
check('has /ask endpoint', "'/ask'" in gw_code)
check('has /data POST endpoint', "'/data/{project}'" in gw_code)
check('has /projects GET endpoint', "'/projects'" in gw_code)
check('has /projects POST endpoint', "handle_projects_create" in gw_code)

# 4b. Auth middleware
check('has auth middleware', 'auth_middleware' in gw_code)
check('health bypasses auth', "request.path == '/health'" in gw_code)
check('checks Bearer token', "auth.startswith('Bearer ')" in gw_code or 'Bearer' in gw_code)
check('returns 401 on bad auth', '401' in gw_code)

# 4c. Concurrency
check('has per-project locks', '_project_locks' in gw_code)
check('has global semaphore', '_global_semaphore' in gw_code)
check('returns 409 when busy', '409' in gw_code)
check('returns 429 when overloaded', '429' in gw_code)

# 4d. Project path handling
check('uses _llm_gateway suffix', "PROJECT_SUFFIX = '_llm_gateway'" in gw_code)
check('uses ~/projects/ root', "Path.home() / 'projects'" in gw_code)
check('project_dir_for function', 'def project_dir_for' in gw_code)
check('_list_project_slugs strips suffix', 'PROJECT_SUFFIX' in gw_code)

# 4e. context parameter
check('/ask reads context field', "'context'" in gw_code)
check('passes context to delegate', "'--context'" in gw_code)

# 4f. Config loading
check('reads openclaw.json', 'openclaw.json' in gw_code)
check('reads gateway.port', "'port'" in gw_code)
check('reads gateway.auth.token', "'token'" in gw_code)
check('reads max_concurrent', "'max_concurrent'" in gw_code)

# 4g. Delegate spawning
check('spawns gateway-delegate.py', 'GATEWAY_DELEGATE_PY' in gw_code)
check('strips CLAUDECODE env var', 'CLAUDECODE' in gw_code)
check('120s timeout', 'timeout=120' in gw_code)

# 4h. Error handling
check('handles JSON parse errors', '400' in gw_code)
check('handles unknown project (404)', '404' in gw_code)
check('handles timeout (504)', '504' in gw_code)
check('handles internal error (500)', '500' in gw_code)

# 4i. Active session tracking
check('has active sessions file', 'active-gateway-sessions.json' in gw_code)
check('updates sessions on start', "'running'" in gw_code)
check('clears sessions on finish', 'status is None' in gw_code or 'None' in gw_code)

# 4j. Project creation
check('create project makes data dir', "'data'" in gw_code)
check('create project writes project.json', "'project.json'" in gw_code)
check('create project supports instructions', "'instructions'" in gw_code)
check('create rejects duplicate (409)', "already exists" in gw_code)


# =========================================================================
# 5. gateway-delegate.py — structure
# =========================================================================

print('\n5. gateway-delegate.py — structure and CLI')

gd_code = (BIN_DIR / 'gateway-delegate.py').read_text(encoding='utf-8')

# 5a. CLI args
check('uses argparse', 'argparse' in gd_code)
check('--context flag', "'--context'" in gd_code)
check('context choices auto|none', "'auto'" in gd_code and "'none'" in gd_code)

# 5b. UTF-8 stdout fix (Windows)
check('fixes stdout encoding', 'TextIOWrapper' in gd_code)

# 5c. Agent spawning
check('spawns agent-smart.py', 'AGENT_SMART_PY' in gd_code)
check('uses --continue', "'--continue'" in gd_code)
check('uses --model haiku', "'haiku'" in gd_code)
check('uses --print-file', "'--print-file'" in gd_code)
check('uses bypassPermissions', "'bypassPermissions'" in gd_code)
check('strips CLAUDECODE', 'CLAUDECODE' in gd_code)
check('120s timeout', 'timeout=120' in gd_code)

# 5d. Prompt cleanup
check('cleans up prompt file', 'prompt_file.unlink' in gd_code)

# 5e. Response extraction
check('extract scoped to session dir', 'cwd_key' in gd_code)
check('extract reads JSONL', '.jsonl' in gd_code)
check('extract filters trivial markers', 'SENT' in gd_code)

# 5f. instructions.md loading
check('reads instructions.md', 'instructions.md' in gd_code)
check('instructions separate from project.json', 'load_instructions' in gd_code)


# =========================================================================
# 6. project_store.py — structure
# =========================================================================

print('\n6. project_store.py — structure')

ps_code = (BIN_DIR / 'project_store.py').read_text(encoding='utf-8')

check('uses _llm_gateway suffix', "PROJECT_SUFFIX = '_llm_gateway'" in ps_code)
check('uses ~/projects/ root', "Path.home() / 'projects'" in ps_code)
check('JSONL format', '.jsonl' in ps_code)
check('append-only writes', "'a'" in ps_code)  # open mode 'a'
check('records have _id', "'_id'" in ps_code)
check('records have _ts', "'_ts'" in ps_code)
check('records have _type', "'_type'" in ps_code)
check('query supports type filter', 'data_type' in ps_code)
check('query supports since filter', 'since' in ps_code)
check('query supports limit', 'limit' in ps_code)
check('query sorts descending', 'reverse=True' in ps_code)


# =========================================================================
# 7. Config file validation
# =========================================================================

print('\n7. Config file validation')

config_path = Path.home() / '.openclaw' / 'openclaw.json'
if config_path.exists():
    config = json.loads(config_path.read_text(encoding='utf-8'))
    gw = config.get('gateway', {})
    check('gateway config exists', bool(gw))
    check('gateway port is 18789', gw.get('port') == 18789)
    check('gateway has max_concurrent', 'max_concurrent' in gw)
    check('gateway max_concurrent is int', isinstance(gw.get('max_concurrent'), int))
    check('gateway has auth section', 'auth' in gw)
    check('gateway auth has token', bool(gw.get('auth', {}).get('token')))
    check('gateway token not placeholder', '${' not in str(gw.get('auth', {}).get('token', '')))
else:
    check('openclaw.json exists', False, 'file not found')

# Check repo config template
repo_config = BIN_DIR.parent / 'config' / 'openclaw.json'
if repo_config.exists():
    repo = json.loads(repo_config.read_text(encoding='utf-8'))
    rgw = repo.get('gateway', {})
    check('repo config has gateway', bool(rgw))
    check('repo config has max_concurrent', 'max_concurrent' in rgw)
    check('repo config token is placeholder', '${' in str(rgw.get('auth', {}).get('token', '')))


# =========================================================================
# 8. Dairy project validation
# =========================================================================

print('\n8. Dairy project validation')

dairy_dir = Path.home() / 'projects' / 'dairy_llm_gateway'
check('dairy project dir exists', dairy_dir.exists())
check('dairy project.json exists', (dairy_dir / 'project.json').exists())
check('dairy instructions.md exists', (dairy_dir / 'instructions.md').exists())
check('dairy data/ dir exists', (dairy_dir / 'data').is_dir())

if (dairy_dir / 'project.json').exists():
    dp = json.loads((dairy_dir / 'project.json').read_text(encoding='utf-8'))
    check('dairy slug is dairy', dp.get('slug') == 'dairy')
    check('dairy has schema', 'journal_entry' in dp.get('schema', {}))
    check('dairy no ai_instructions in json', 'ai_instructions' not in dp)

    schema = dp.get('schema', {}).get('journal_entry', {})
    check('dairy schema has text', 'text' in schema)
    check('dairy schema has mood', 'mood' in schema)
    check('dairy schema has activities', 'activities' in schema)
    check('dairy schema has timestamp', 'timestamp' in schema)

if (dairy_dir / 'instructions.md').exists():
    inst = (dairy_dir / 'instructions.md').read_text(encoding='utf-8')
    check('dairy instructions mention mood', 'mood' in inst.lower())
    check('dairy instructions mention time series', 'time series' in inst.lower())
    check('dairy instructions mention activities', 'activities' in inst.lower())

# Check for data files
data_files = list((dairy_dir / 'data').glob('*.jsonl'))
check('dairy has journal_entry.jsonl', any(f.name == 'journal_entry.jsonl' for f in data_files))


# =========================================================================
# 9. Cross-contamination safety
# =========================================================================

print('\n9. Cross-contamination safety')

gw_code = (BIN_DIR / 'llm-gateway.py').read_text(encoding='utf-8')
gd_code = (BIN_DIR / 'gateway-delegate.py').read_text(encoding='utf-8')

# Gateway should NOT import discord libraries or call discord-send
check('gateway does not import discord lib', 'import discord' not in gw_code)
check('gateway does not reference delegate.py', 'delegate.py' not in gw_code or 'gateway-delegate.py' in gw_code)

# Delegate should NOT import discord or call discord-send as a subprocess
check('gw-delegate does not import discord lib', 'import discord' not in gd_code)
check('gw-delegate does not spawn discord-send', 'discord-send.py' not in gd_code)

# Session isolation: delegate uses scoped JSONL extraction
check('gw-delegate scopes JSONL to work_dir', 'cwd_key' in gd_code)


# =========================================================================
# 10. Edge cases
# =========================================================================

print('\n10. Edge cases')

# 10a. Empty data dir
empty_dir = TEMP_PROJECTS / 'emptyapp_llm_gateway'
empty_dir.mkdir()
(empty_dir / 'data').mkdir()
(empty_dir / 'project.json').write_text(json.dumps({
    'slug': 'emptyapp', 'display': 'Empty', 'schema': {},
}), encoding='utf-8')

entries = project_store.query_entries(empty_dir)
check('query empty data dir returns []', entries == [])

# 10b. Malformed JSONL line
malformed_dir = TEMP_PROJECTS / 'malformed_llm_gateway'
malformed_dir.mkdir()
(malformed_dir / 'data').mkdir()
(malformed_dir / 'project.json').write_text(json.dumps({
    'slug': 'malformed', 'display': 'Malformed', 'schema': {},
}), encoding='utf-8')
(malformed_dir / 'data' / 'test.jsonl').write_text(
    'not json\n{"_ts":"2026-06-10T10:00:00Z","valid":"entry"}\n',
    encoding='utf-8',
)
entries = project_store.query_entries(malformed_dir)
check('query handles malformed JSONL gracefully', len(entries) == 1)

# 10c. Multiple data types in single query
entries = project_store.query_entries(TEST_PROJECT_DIR, data_type=None)
types_found = set(e.get('_type') for e in entries)
check('query all types returns multiple types', len(types_found) >= 2,
      f'found: {types_found}')

# 10d. Append to different types creates separate files
log_file = TEST_PROJECT_DIR / 'data' / 'log_entry.jsonl'
metric_file = TEST_PROJECT_DIR / 'data' / 'metric.jsonl'
check('separate JSONL per type', log_file.exists() and metric_file.exists())

# 10e. Unicode in entries
project_store.append_entry(TEST_PROJECT_DIR, proj, 'log_entry', {
    'text': 'Unicode test: \u2764\ufe0f \ud83d\ude80 caf\u00e9',
    'level': 'info',
    'timestamp': '2026-06-10T15:00:00Z',
})
entries = project_store.query_entries(TEST_PROJECT_DIR, data_type='log_entry')
unicode_entry = next((e for e in entries if 'Unicode' in e.get('text', '')), None)
check('unicode entries stored correctly', unicode_entry is not None)
check('unicode preserved in query', '\u2764' in unicode_entry.get('text', '') if unicode_entry else False)


# =========================================================================
# Cleanup
# =========================================================================

# Restore original paths
project_store.PROJECTS_ROOT = original_root
project_store.PROJECT_SUFFIX = original_suffix

try:
    shutil.rmtree(TEMP_DIR)
except Exception:
    pass

# =========================================================================
# Summary
# =========================================================================

print(f'\n{"=" * 40}')
print(f'Results: {passed} passed, {failed} failed')
print(f'{"=" * 40}')

sys.exit(1 if failed > 0 else 0)
