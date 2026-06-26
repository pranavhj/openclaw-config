#!/usr/bin/env python3
"""llm-gateway.py — HTTP server for app-to-Claude communication.

Runs on the PC (Tailscale IP), accepts requests from Android apps.
Per-project locks + global semaphore for concurrency control.
Detailed JSONL timeline logging with per-request session IDs.

Usage: python llm-gateway.py [--port PORT]
"""
import asyncio
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web

# ---------------------------------------------------------------------------
# Paths & Config
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
GATEWAY_DELEGATE_PY = SCRIPT_DIR / 'gateway-delegate.py'

CONFIG_PATH = Path.home() / '.openclaw' / 'openclaw.json'
PROJECTS_ROOT = Path.home() / 'projects'
PROJECT_SUFFIX = '_llm_gateway'
LOGDIR = Path(os.getenv('LOCALAPPDATA') or '/tmp') / 'openclaw'
ACTIVE_SESSIONS_FILE = LOGDIR / 'active-gateway-sessions.json'


def project_dir_for(slug: str) -> Path:
    """Map project slug to its directory: ~/projects/<slug>_llm_gateway/"""
    return PROJECTS_ROOT / f'{slug}{PROJECT_SUFFIX}'


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [gateway] %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('gateway')


def load_config():
    with open(CONFIG_PATH, encoding='utf-8') as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Timeline logging (JSONL + human-readable, like delegate.py)
# ---------------------------------------------------------------------------

_request_counter = 0


def _new_session_id() -> str:
    """Short session ID: gw-XXXX (8 hex chars). Unique per request."""
    return 'gw-' + uuid.uuid4().hex[:8]


def _ts_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime('%Y-%m-%dT%H:%M:%S.') + f'{now.microsecond // 1000:03d}Z'


def _tl(event: dict):
    """Append a JSONL event to the gateway timeline log."""
    try:
        today = datetime.now().strftime('%Y-%m-%d')  # local time for file date
        tl_path = LOGDIR / f'gateway-timeline-{today}.log'
        with open(tl_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(event) + '\n')
    except Exception:
        pass


def _log_human(text: str):
    """Append a human-readable line to the gateway log."""
    try:
        today = datetime.now().strftime('%Y-%m-%d')  # local time for file date
        log_path = LOGDIR / f'gateway-{today}.log'
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f'{now_str} {text}\n')
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Concurrency primitives (created per-app instance)
# ---------------------------------------------------------------------------

_project_locks: dict[str, asyncio.Lock] = {}
_global_semaphore: asyncio.Semaphore | None = None
_semaphore_max: int = 3


def get_project_lock(slug: str) -> asyncio.Lock:
    if slug not in _project_locks:
        _project_locks[slug] = asyncio.Lock()
    return _project_locks[slug]


def _semaphore_state() -> str:
    """Return 'used/max' string showing semaphore usage."""
    if _global_semaphore is None:
        return '?/?'
    used = _semaphore_max - _global_semaphore._value
    return f'{used}/{_semaphore_max}'


def _active_projects() -> list[str]:
    """Return list of currently locked project slugs."""
    return [slug for slug, lock in _project_locks.items() if lock.locked()]


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

AUTH_TOKEN: str = ''


@web.middleware
async def auth_middleware(request: web.Request, handler):
    # /health is public
    if request.path == '/health':
        return await handler(request)

    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer ') or auth[7:] != AUTH_TOKEN:
        sid = request.get('session_id', '?')
        client = request.remote or '?'
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'auth_rejected',
             'path': request.path, 'method': request.method, 'client': client})
        log.warning('[%s] auth rejected: %s %s from %s', sid, request.method, request.path, client)
        return web.json_response(
            {'status': 'error', 'error': 'Unauthorized'},
            status=401,
        )
    return await handler(request)


# ---------------------------------------------------------------------------
# Request ID middleware — assigns a session ID to every request
# ---------------------------------------------------------------------------

@web.middleware
async def request_id_middleware(request: web.Request, handler):
    global _request_counter
    _request_counter += 1
    sid = _new_session_id()
    request['session_id'] = sid
    request['request_num'] = _request_counter
    request['t0'] = time.monotonic()

    client = request.remote or '?'
    _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'request_received', 'num': _request_counter,
         'method': request.method, 'path': request.path, 'client': client,
         'content_length': request.content_length or 0})

    try:
        response = await handler(request)
        duration_ms = int((time.monotonic() - request['t0']) * 1000)
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'request_done',
             'status': response.status, 'duration_ms': duration_ms,
             'response_size': response.content_length or 0})
        return response
    except Exception as e:
        duration_ms = int((time.monotonic() - request['t0']) * 1000)
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'request_error',
             'error': str(e)[:200], 'duration_ms': duration_ms})
        raise


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def handle_health(request: web.Request):
    sid = request.get('session_id', '?')
    active = _active_projects()
    _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'health_check',
         'active_projects': active, 'semaphore': _semaphore_state()})
    return web.json_response({
        'status': 'ok',
        'active_sessions': len(active),
        'projects': _list_project_slugs(),
    })


async def handle_ask(request: web.Request):
    sid = request.get('session_id', '?')

    try:
        body = await request.json()
    except Exception as e:
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'ask_bad_json', 'error': str(e)[:100]})
        log.warning('[%s] /ask bad JSON', sid)
        return web.json_response(
            {'status': 'error', 'error': 'Invalid JSON'}, status=400,
        )

    project = body.get('project', '').strip()
    message = body.get('message', '').strip()

    if not project or not message:
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'ask_missing_fields',
             'has_project': bool(project), 'has_message': bool(message)})
        log.warning('[%s] /ask missing fields', sid)
        return web.json_response(
            {'status': 'error', 'error': 'project and message required'},
            status=400,
        )

    context = body.get('context', 'auto')  # "auto" or "none"

    client = request.remote or '?'
    _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'ask_received',
         'project': project, 'context': context, 'client': client,
         'msg_len': len(message), 'msg_preview': message[:120]})
    _log_human(f'[{sid}] ASK from={client} project={project} context={context} msg={message[:100]}')
    log.info('[%s] ask: client=%s project=%s context=%s msg=%s', sid, client, project, context, message[:80])

    # Check project exists
    pdir = project_dir_for(project)
    if not (pdir / 'project.json').exists():
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'ask_project_not_found', 'project': project})
        log.warning('[%s] project not found: %s', sid, project)
        return web.json_response(
            {'status': 'error', 'error': f'Unknown project: {project}'},
            status=404,
        )

    # Per-project lock (non-blocking)
    lock = get_project_lock(project)
    if lock.locked():
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'ask_project_busy',
             'project': project, 'active': _active_projects()})
        log.info('[%s] project busy: %s (active: %s)', sid, project, _active_projects())
        return web.json_response(
            {'status': 'busy', 'error': 'Project already processing',
             'retry_after_ms': 5000},
            status=409,
        )

    async with lock:
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'ask_lock_acquired',
             'project': project, 'semaphore': _semaphore_state()})

        # Global semaphore
        try:
            await asyncio.wait_for(_global_semaphore.acquire(), timeout=1.0)
        except asyncio.TimeoutError:
            _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'ask_semaphore_full',
                 'project': project, 'active': _active_projects()})
            log.warning('[%s] semaphore full: %s (active: %s)', sid, project, _active_projects())
            return web.json_response(
                {'status': 'busy', 'error': 'Too many concurrent sessions',
                 'retry_after_ms': 10000},
                status=429,
            )

        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'ask_semaphore_acquired',
             'project': project, 'semaphore': _semaphore_state()})

        try:
            t0 = time.monotonic()
            _update_active_sessions(project, 'running', sid)

            _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'delegate_spawn',
                 'project': project, 'context': context})
            log.info('[%s] spawning delegate: project=%s', sid, project)

            # Run gateway-delegate in a thread (it's blocking subprocess work)
            response_text = await asyncio.get_event_loop().run_in_executor(
                None, _run_delegate, project, message, context, sid,
            )

            duration_ms = int((time.monotonic() - t0) * 1000)
            resp_len = len(response_text)

            _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'ask_success',
                 'project': project, 'duration_ms': duration_ms,
                 'response_len': resp_len, 'response_preview': response_text[:120]})
            _log_human(f'[{sid}] DONE project={project} duration={duration_ms}ms response={resp_len}ch')
            log.info('[%s] ask done: project=%s duration=%dms response=%dch',
                     sid, project, duration_ms, resp_len)

            return web.json_response({
                'status': 'ok',
                'response': response_text,
                'duration_ms': duration_ms,
            })
        except TimeoutError:
            _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'ask_timeout', 'project': project})
            _log_human(f'[{sid}] TIMEOUT project={project}')
            log.error('[%s] ask timeout: project=%s', sid, project)
            return web.json_response(
                {'status': 'error', 'error': 'Request timed out'},
                status=504,
            )
        except Exception as e:
            _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'ask_error',
                 'project': project, 'error': str(e)[:300]})
            _log_human(f'[{sid}] ERROR project={project} error={str(e)[:200]}')
            log.exception('[%s] ask failed: project=%s', sid, project)
            return web.json_response(
                {'status': 'error', 'error': str(e)},
                status=500,
            )
        finally:
            _global_semaphore.release()
            _update_active_sessions(project, None)
            _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'ask_cleanup',
                 'project': project, 'semaphore': _semaphore_state(),
                 'active': _active_projects()})


async def handle_data_post(request: web.Request):
    sid = request.get('session_id', '?')
    project = request.match_info['project']
    pdir = project_dir_for(project)

    if not (pdir / 'project.json').exists():
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'data_post_project_not_found', 'project': project})
        return web.json_response(
            {'status': 'error', 'error': f'Unknown project: {project}'},
            status=404,
        )

    try:
        body = await request.json()
    except Exception as e:
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'data_post_bad_json',
             'project': project, 'error': str(e)[:100]})
        return web.json_response(
            {'status': 'error', 'error': 'Invalid JSON'}, status=400,
        )

    data_type = body.get('type', '').strip()
    data = body.get('data')
    if not data_type or not data:
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'data_post_missing_fields',
             'project': project, 'has_type': bool(data_type), 'has_data': bool(data)})
        return web.json_response(
            {'status': 'error', 'error': 'type and data required'},
            status=400,
        )

    client = request.remote or '?'
    _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'data_post_received',
         'project': project, 'data_type': data_type, 'client': client,
         'data_keys': list(data.keys()) if isinstance(data, dict) else '?'})

    from project_store import append_entry, load_project

    try:
        proj = load_project(pdir)
        entry_id = append_entry(pdir, proj, data_type, data)
    except ValueError as e:
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'data_post_validation_error',
             'project': project, 'data_type': data_type, 'error': str(e)})
        log.warning('[%s] data validation failed: project=%s type=%s error=%s', sid, project, data_type, e)
        return web.json_response(
            {'status': 'error', 'error': str(e)}, status=400,
        )
    except Exception as e:
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'data_post_error',
             'project': project, 'data_type': data_type, 'error': str(e)[:200]})
        log.exception('[%s] data store failed: project=%s', sid, project)
        return web.json_response(
            {'status': 'error', 'error': str(e)}, status=500,
        )

    _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'data_post_stored',
         'project': project, 'data_type': data_type, 'entry_id': entry_id})
    log.info('[%s] data stored: project=%s type=%s id=%s', sid, project, data_type, entry_id)
    return web.json_response({'status': 'ok', 'id': entry_id})


async def handle_data_get(request: web.Request):
    sid = request.get('session_id', '?')
    project = request.match_info['project']
    pdir = project_dir_for(project)

    if not (pdir / 'project.json').exists():
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'data_get_project_not_found', 'project': project})
        return web.json_response(
            {'status': 'error', 'error': f'Unknown project: {project}'},
            status=404,
        )

    data_type = request.query.get('type')
    since = request.query.get('since')
    limit = int(request.query.get('limit', '50'))

    client = request.remote or '?'
    _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'data_get_query',
         'project': project, 'data_type': data_type, 'since': since, 'limit': limit,
         'client': client})

    from project_store import query_entries

    entries = query_entries(pdir, data_type=data_type, since=since, limit=limit)

    _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'data_get_result',
         'project': project, 'count': len(entries)})
    log.info('[%s] data query: project=%s type=%s count=%d', sid, project, data_type, len(entries))
    return web.json_response({'status': 'ok', 'entries': entries, 'count': len(entries)})


async def handle_projects_list(request: web.Request):
    sid = request.get('session_id', '?')
    slugs = _list_project_slugs()
    projects = []
    for slug in slugs:
        pdir = project_dir_for(slug)
        pj = pdir / 'project.json'
        if pj.exists():
            try:
                proj = json.loads(pj.read_text(encoding='utf-8'))
                projects.append({
                    'slug': slug,
                    'display': proj.get('display', slug),
                    'data_types': list(proj.get('schema', {}).keys()),
                })
            except Exception:
                projects.append({'slug': slug, 'display': slug, 'data_types': []})
    _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'projects_list', 'count': len(projects)})
    log.info('[%s] projects list: %d projects', sid, len(projects))
    return web.json_response({'status': 'ok', 'projects': projects})


async def handle_projects_create(request: web.Request):
    sid = request.get('session_id', '?')

    try:
        body = await request.json()
    except Exception as e:
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'project_create_bad_json', 'error': str(e)[:100]})
        return web.json_response(
            {'status': 'error', 'error': 'Invalid JSON'}, status=400,
        )

    slug = body.get('slug', '').strip()
    if not slug:
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'project_create_missing_slug'})
        return web.json_response(
            {'status': 'error', 'error': 'slug required'}, status=400,
        )

    pdir = project_dir_for(slug)
    if (pdir / 'project.json').exists():
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'project_create_duplicate', 'slug': slug})
        log.warning('[%s] project create duplicate: %s', sid, slug)
        return web.json_response(
            {'status': 'error', 'error': f'Project {slug} already exists'},
            status=409,
        )

    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / 'data').mkdir(exist_ok=True)

    project_data = {
        'slug': slug,
        'display': body.get('display', slug),
        'schema': body.get('schema', {}),
    }
    (pdir / 'project.json').write_text(
        json.dumps(project_data, indent=2), encoding='utf-8',
    )

    # Create instructions.md if provided
    instructions = body.get('instructions', '')
    if instructions:
        (pdir / 'instructions.md').write_text(instructions, encoding='utf-8')

    _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'project_created',
         'slug': slug, 'path': str(pdir), 'has_instructions': bool(instructions),
         'schema_types': list(body.get('schema', {}).keys())})
    _log_human(f'[{sid}] PROJECT CREATED slug={slug} path={pdir}')
    log.info('[%s] project created: %s at %s', sid, slug, pdir)
    return web.json_response({'status': 'ok', 'slug': slug, 'path': str(pdir)}, status=201)


# ---------------------------------------------------------------------------
# Delegate runner (blocking — called via run_in_executor)
# ---------------------------------------------------------------------------

def _run_delegate(project: str, message: str, context: str = 'auto', sid: str = '?') -> str:
    """Spawn gateway-delegate.py and capture Claude's response."""
    import subprocess

    _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'delegate_subprocess_start',
         'project': project, 'context': context, 'pid': os.getpid()})

    t0 = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(GATEWAY_DELEGATE_PY), '--context', context, '--sid', sid, project, message],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=120,
        env={k: v for k, v in os.environ.items() if k != 'CLAUDECODE'},
    )

    duration_ms = int((time.monotonic() - t0) * 1000)
    stdout_len = len(result.stdout)
    stderr_len = len(result.stderr)

    _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'delegate_subprocess_done',
         'project': project, 'exit_code': result.returncode,
         'duration_ms': duration_ms, 'stdout_len': stdout_len, 'stderr_len': stderr_len,
         'stderr_preview': result.stderr.strip()[:200] if result.stderr.strip() else ''})

    if result.returncode != 0:
        stderr = result.stderr.strip()
        _tl({'ts': _ts_iso(), 'sid': sid, 'event': 'delegate_failed',
             'project': project, 'exit_code': result.returncode, 'stderr': stderr[:500]})
        raise RuntimeError(f'Delegate failed (exit {result.returncode}): {stderr[:200]}')

    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _list_project_slugs() -> list[str]:
    """List project slugs by finding *_llm_gateway dirs with project.json."""
    if not PROJECTS_ROOT.exists():
        return []
    return sorted(
        d.name[:-len(PROJECT_SUFFIX)]
        for d in PROJECTS_ROOT.iterdir()
        if d.is_dir() and d.name.endswith(PROJECT_SUFFIX) and (d / 'project.json').exists()
    )


def _update_active_sessions(project: str, status: str | None, sid: str = '?'):
    """Update the active-gateway-sessions.json file for discord-bot monitoring."""
    try:
        sessions = {}
        if ACTIVE_SESSIONS_FILE.exists():
            sessions = json.loads(ACTIVE_SESSIONS_FILE.read_text(encoding='utf-8'))

        if status is None:
            sessions.pop(project, None)
        else:
            sessions[project] = {
                'status': status,
                'sid': sid,
                'ts': time.time(),
            }

        ACTIVE_SESSIONS_FILE.write_text(
            json.dumps(sessions, indent=2), encoding='utf-8',
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

def create_app() -> web.Application:
    app = web.Application(middlewares=[request_id_middleware, auth_middleware])

    app.router.add_get('/health', handle_health)
    app.router.add_post('/ask', handle_ask)
    app.router.add_post('/data/{project}', handle_data_post)
    app.router.add_get('/data/{project}', handle_data_get)
    app.router.add_get('/projects', handle_projects_list)
    app.router.add_post('/projects', handle_projects_create)

    return app


def main():
    global AUTH_TOKEN, _global_semaphore, _semaphore_max

    LOGDIR.mkdir(parents=True, exist_ok=True)

    config = load_config()
    gateway_config = config.get('gateway', {})
    port = gateway_config.get('port', 18789)
    max_concurrent = gateway_config.get('max_concurrent', 3)
    AUTH_TOKEN = gateway_config.get('auth', {}).get('token', '')

    if not AUTH_TOKEN:
        log.error('No gateway auth token configured in openclaw.json')
        sys.exit(1)

    # Parse CLI args
    import argparse
    parser = argparse.ArgumentParser(description='LLM Gateway')
    parser.add_argument('--port', type=int, default=port)
    args = parser.parse_args()

    _semaphore_max = max_concurrent
    _global_semaphore = asyncio.Semaphore(max_concurrent)

    # Add project_store to import path
    sys.path.insert(0, str(SCRIPT_DIR))

    _tl({'ts': _ts_iso(), 'sid': 'startup', 'event': 'gateway_start',
         'port': args.port, 'max_concurrent': max_concurrent, 'pid': os.getpid(),
         'projects': _list_project_slugs()})
    _log_human(f'[startup] Gateway starting on port {args.port} (max_concurrent={max_concurrent}, pid={os.getpid()})')

    log.info('Starting LLM Gateway on port %d (max_concurrent=%d, pid=%d)', args.port, max_concurrent, os.getpid())
    log.info('Projects root: %s', PROJECTS_ROOT)
    log.info('Projects: %s', _list_project_slugs() or '(none)')
    log.info('Log dir: %s', LOGDIR)

    app = create_app()
    web.run_app(app, host='0.0.0.0', port=args.port, print=lambda msg: log.info(msg))


if __name__ == '__main__':
    main()
