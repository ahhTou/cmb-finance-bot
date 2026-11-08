#!/usr/bin/env python3
"""Local HTTP API for the management app.

Every call runs `src/admin_cli.py` in a child process, exactly as the native app
did, so locks, checks and error messages stay in one place. Listens on
127.0.0.1 only and requires a bearer token; request bodies are never logged.
"""
import argparse
import asyncio
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time
from typing import Dict, List, Literal, Optional

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool
import uvicorn

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / 'var' / 'night' / 'watch.log'
SCREENSHOT = ROOT / 'var' / 'screenshots' / 'current.png'
DEV_STATE = ROOT / 'var' / 'admin-server.json'
ORIGINS = ['tauri://localhost', 'http://tauri.localhost',
           'http://localhost:5173', 'http://127.0.0.1:5173']
EVENT_INTERVAL_S = 3

config = {'token': os.environ.get('CMB_ADMIN_TOKEN') or secrets.token_urlsafe(32),
          'python': os.environ.get('CMB_PYTHON') or '/usr/bin/python3'}


class Failure(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def timeout(args):
    if args[0] == 'emulator':
        return 60 if 'start' in args else 30
    # plan-disarm may wait ~10 s for the plan worker plus ~10 s for the current
    # watch plus adb close time; 30 s could 504 halfway through.
    if args[0] == 'plan-disarm':
        return 60
    return {'cancel': 300, 'buy': 420}.get(args[0], 30)


def run(args, payload=None):
    """Run one admin_cli command; return its JSON or raise Failure with its message."""
    try:
        proc = subprocess.run([config['python'], '-B', 'src/admin_cli.py', *args], cwd=str(ROOT),
                              input=json.dumps(payload) if payload is not None else '',
                              capture_output=True, text=True, timeout=timeout(args))
    except subprocess.TimeoutExpired:
        raise Failure(504, '操作超时，请刷新状态后再决定下一步。')
    except OSError:
        raise Failure(500, '无法启动 Python，请检查设置中的 Python 路径。')
    try:
        data = json.loads(proc.stdout)
        if not isinstance(data, dict): raise ValueError()
    except ValueError:
        raise Failure(502, '后端返回格式无效。')
    if proc.returncode != 0 or data.get('ok') is not True:
        raise Failure(400, data.get('error') or '操作失败。')
    return data


app = FastAPI(title='cmb-finance-bot admin', docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=['*'],
                   allow_headers=['Authorization', 'Content-Type'])


@app.middleware('http')
async def require_token(request: Request, call_next):
    if request.url.path.startswith('/api/') and request.url.path != '/api/health' \
            and request.method != 'OPTIONS':
        given = request.headers.get('authorization', '')
        if not hmac.compare_digest(given, 'Bearer ' + config['token']):
            return JSONResponse({'error': '未授权。'}, status_code=401)
    return await call_next(request)


@app.exception_handler(Failure)
async def failure(_, exc: Failure):
    return JSONResponse({'error': str(exc)}, status_code=exc.status)


class ArmRequest(BaseModel):
    code: str
    amount: str
    at: Optional[str] = None
    now: bool = False
    dry_run: bool = False
    confirm_real_payment: bool = False
    prep_minutes: Optional[int] = None
    settings_revision: Optional[str] = None
    mode: Literal['first_launch', 'redemption'] = 'first_launch'


class BuyRequest(BaseModel):
    code: str
    amount: str
    real: bool = False


class CancelRequest(BaseModel):
    amount: str = '0.01'
    limit: int = 0
    action: Literal['list', 'dry_run', 'real'] = 'list'


class FavoriteRequest(BaseModel):
    code: str
    title: str = ''


class FavoriteTestRequest(BaseModel):
    code: str
    amount: str


class QuotaTimeRequest(BaseModel):
    id: Optional[str] = None
    kind: Literal['issue', 'bargain', 'regular']
    date: Optional[str] = None
    time: str
    weekdays: List[int] = Field(default_factory=list)
    amount_wan: Optional[str] = None
    note: str = ''


class FavoriteSettingsRequest(BaseModel):
    title: Optional[str] = None
    test_amount: Optional[str] = None
    quota_times: Optional[List[QuotaTimeRequest]] = None


class PatternRequest(BaseModel):
    new: str


class PasswordRequest(BaseModel):
    current: str
    new: str


class PushPreferencesRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: StrictBool = True
    events: Dict[str, StrictBool] = Field(default_factory=dict)


class PushRequest(BaseModel):
    server: str
    topic: str
    # Empty means "keep the saved token"; the first save needs a non-empty one.
    token: str = ''


class PlanItemRequest(BaseModel):
    code: str
    amount: str
    at: str
    mode: Literal['first_launch', 'redemption'] = 'first_launch'


class PlanRequest(BaseModel):
    dry_run: bool = False
    items: List[PlanItemRequest]


class PlanStartRequest(BaseModel):
    plan_id: str
    content_revision: str
    settings_revision: str
    confirm_real_payment: bool = False


@app.get('/api/health')
def health():
    return {'ok': True}


@app.get('/api/info')
def info():
    return {'root': str(ROOT), 'python': config['python'], 'log_path': str(LOG),
            'skill_path': str(ROOT / 'skills' / 'cmb-watch' / 'SKILL.md')}


@app.get('/api/status')
def status():
    return run(['status'])


@app.get('/api/device')
def device():
    return run(['device'])


@app.get('/api/system')
def system():
    return run(['system'])


@app.get('/api/history')
def history(limit: int = 0):
    return run(['history', '--limit', str(limit)])


@app.get('/api/log')
def log(lines: int = 800):
    return run(['log', '--lines', str(lines)])


@app.get('/api/settings')
def settings():
    return run(['settings'])


@app.put('/api/settings')
def save_settings(values: Dict[str, int]):
    args = ['settings']
    for key, value in values.items():
        if not re.fullmatch(r'[a-z_]{1,40}', key):
            raise Failure(400, '配置项名称无效。')
        args += ['--' + key.replace('_', '-'), str(value)]
    return run(args)


@app.get('/api/settings/other')
def settings_other():
    return run(['settings-other'])


@app.put('/api/settings/other')
def save_settings_other(values: Dict[str, int]):
    args = ['settings-other']
    for key, value in values.items():
        if not re.fullmatch(r'[a-z_]{1,40}', key):
            raise Failure(400, '配置项名称无效。')
        args += ['--' + key.replace('_', '-'), str(value)]
    return run(args)


@app.post('/api/arm')
def arm(body: ArmRequest):
    args = ['arm', '--code', body.code, '--amount', body.amount, '--mode', body.mode]
    args += ['--now'] if body.now else ['--at', body.at or '']
    if body.prep_minutes is not None: args += ['--prep-minutes', str(body.prep_minutes)]
    if body.settings_revision: args += ['--settings-revision', body.settings_revision]
    if body.dry_run: args.append('--dry-run')
    if body.confirm_real_payment: args.append('--confirm-real-payment')
    return run(args)


@app.get('/api/push/preferences')
def push_preferences():
    return run(['push-preferences'])


@app.put('/api/push/preferences')
def save_push_preferences(body: PushPreferencesRequest):
    return run(['push-preferences-save'], body.model_dump(exclude_unset=True))


@app.get('/api/plan')
def plan():
    return run(['plan'])


@app.put('/api/plan')
def save_plan(body: PlanRequest):
    return run(['plan-save'], {'dry_run': body.dry_run,
                               'items': [item.model_dump() for item in body.items]})


@app.post('/api/plan/start')
def start_plan(body: PlanStartRequest):
    args = ['plan-start', '--plan-id', body.plan_id,
            '--content-revision', body.content_revision,
            '--settings-revision', body.settings_revision]
    if body.confirm_real_payment:
        args.append('--confirm-real-payment')
    return run(args)


@app.post('/api/plan/disarm')
def disarm_plan():
    return run(['plan-disarm'])


@app.delete('/api/plan')
def clear_plan():
    return run(['plan-clear'])


@app.post('/api/disarm')
def disarm():
    return run(['disarm'])


@app.post('/api/keep-awake')
def keep_awake():
    return run(['keep-awake'])


@app.post('/api/screenshot')
def screenshot():
    return run(['screenshot'])


@app.get('/api/screenshot.png')
def screenshot_file():
    if not SCREENSHOT.exists():
        raise Failure(404, '还没有截图。')
    return FileResponse(str(SCREENSHOT), media_type='image/png', headers={'Cache-Control': 'no-store'})


@app.post('/api/emulator/{action}')
def emulator(action: Literal['start', 'stop']):
    return run(['emulator', action])


@app.post('/api/buy')
def buy(body: BuyRequest):
    return run(['buy', '--code', body.code, '--amount', body.amount,
                '--confirm-real-payment' if body.real else '--dry-run'])


@app.post('/api/cancel')
def cancel(body: CancelRequest):
    args = ['cancel', '--amount', body.amount]
    if body.limit: args += ['--limit', str(body.limit)]
    args.append({'list': '--list', 'dry_run': '--dry-run', 'real': '--yes'}[body.action])
    return run(args)


@app.get('/api/favorites')
def favorites():
    return run(['favorites', '--list'])


@app.post('/api/favorites')
def add_favorite(body: FavoriteRequest):
    return run(['favorites', '--add', body.code, '--title', body.title])


@app.put('/api/favorites/{code}')
def update_favorite(code: str, body: FavoriteSettingsRequest):
    """Save one favourite's settings; only explicitly sent keys are applied."""
    payload = {'code': code}
    if body.title is not None:
        payload['title'] = body.title
    if 'test_amount' in body.model_fields_set:
        # An explicit null clears this item's test flag; omitted keeps it.
        payload['test_amount'] = body.test_amount
    if body.quota_times is not None:
        payload['quota_times'] = [
            entry.model_dump(exclude_none=True) for entry in body.quota_times
        ]
    return run(['favorites', '--save'], payload)


# Declared before /api/favorites/{code}: a DELETE to /api/favorites/test must
# clear the test item instead of removing a favourite called "test".
@app.post('/api/favorites/test')
def set_favorite_test(body: FavoriteTestRequest):
    return run(['favorites', '--set-test', body.code, '--test-amount', body.amount])


@app.delete('/api/favorites/test')
def clear_favorite_test():
    return run(['favorites', '--clear-test'])


@app.delete('/api/favorites/{code}')
def remove_favorite(code: str):
    return run(['favorites', '--remove', code])


@app.post('/api/credentials/login-pattern')
def set_pattern(body: PatternRequest):
    return run(['set-login-pattern'], {'new': body.new})


@app.post('/api/credentials/payment-password')
def set_password(body: PasswordRequest):
    return run(['set-payment-password'], {'current': body.current, 'new': body.new})


@app.get('/api/push')
def push_config():
    return run(['push'])


@app.put('/api/push')
def save_push_config(body: PushRequest):
    # The token goes through stdin like the other secrets, never argv.
    return run(['push-save'], {'server': body.server, 'topic': body.topic, 'token': body.token})


@app.post('/api/push/test')
def test_push():
    return run(['push-test'])


@app.delete('/api/push')
def clear_push_config():
    return run(['push-clear'])


@app.post('/api/open-log')
def open_log():
    if not LOG.exists():
        raise Failure(404, '日志文件不存在。')
    subprocess.run(['/usr/bin/open', str(LOG)], timeout=5)
    return {'ok': True}


@app.get('/api/events')
async def events(request: Request):
    """Server-sent events: one `status` event right away, then every few seconds."""
    async def stream():
        while not await request.is_disconnected():
            try:
                data = await run_in_threadpool(run, ['status'])
                yield 'event: status\ndata: ' + json.dumps(data, ensure_ascii=False) + '\n\n'
            except Failure as exc:
                yield 'event: failure\ndata: ' + json.dumps({'error': str(exc)}, ensure_ascii=False) + '\n\n'
            await asyncio.sleep(EVENT_INTERVAL_S)
    return StreamingResponse(stream(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-store'})


def main(argv: Optional[List[str]] = None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=int, default=8765)
    p.add_argument('--dev', action='store_true',
                   help='write port and token to var/admin-server.json for the Vite dev proxy')
    p.add_argument('--exit-with-parent', action='store_true',
                   help='exit when the launching app goes away, so a crashed shell leaves no server behind')
    a = p.parse_args(argv)
    if a.exit_with_parent:
        parent = os.getppid()
        def watch_parent():
            while os.getppid() == parent:
                time.sleep(2)
            os._exit(0)
        threading.Thread(target=watch_parent, daemon=True).start()
    if a.dev:
        DEV_STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = DEV_STATE.with_suffix('.tmp')
        tmp.write_text(json.dumps({'port': a.port, 'token': config['token']}), encoding='utf-8')
        tmp.chmod(0o600)
        tmp.replace(DEV_STATE)
    uvicorn.run(app, host='127.0.0.1', port=a.port, log_level='warning', access_log=False)


if __name__ == '__main__':
    main()
