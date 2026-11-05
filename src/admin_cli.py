#!/usr/bin/env python3
"""JSON bridge for the local management app. No credentials in argv or errors."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime
import io
import json
from pathlib import Path
import re
import socket
import ssl
import subprocess
import sys
import time

import night_watch as nw
import keychain_store
import purchase_settings
import favorites

import manage
import notify


def atomic_json(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    tmp.chmod(0o600)
    tmp.replace(path)


def agent_info(task):
    path = nw.STATE / 'agent.json'
    if not task or not path.exists():
        return {'state': 'none'}
    try:
        data = json.loads(path.read_text())
        if data['armed_at'] != task['armed_at']:
            return {'state': 'none'}
        age = (datetime.now() - datetime.fromisoformat(data['last_seen'])).total_seconds()
        return dict(data, state='stale' if age > 2 * data['interval_s'] else 'watching')
    except (ValueError, KeyError, TypeError):
        return {'state': 'none'}


def status():
    data = nw.status_info()
    data.update(agent=agent_info(data['task']), processes=manage.status_info(),
                credentials=keychain_store.credential_info(),
                mail_configured=notify.configured(), log_path=str(nw.LOG),
                favorites=favorites.load(), test_item=favorites.test_item())
    return data


def device():
    result = manage.status_info()
    queries = {'booted': ('getprop', 'sys.boot_completed'), 'app_pid': ('pidof', nw.PACKAGE),
               'resolution': ('wm', 'size'), 'power': ('dumpsys', 'power'),
               'stay_on': ('settings', 'get', 'global', 'stay_on_while_plugged_in'),
               'battery': ('dumpsys', 'battery'),
               'screen_timeout': ('settings', 'get', 'system', 'screen_off_timeout'),
               'lock_disabled': ('locksettings', 'get-disabled')}
    def query(item):
        key, args = item
        try:
            return key, nw.adb('shell', *args, timeout=5).strip()
        except (OSError, subprocess.SubprocessError):
            return key, '无法读取'
    if not result['emulator']['running']:
        return dict(result, booted=False)
    with ThreadPoolExecutor(max_workers=8) as pool:
        result.update(dict(pool.map(query, queries.items())))
    result['booted'] = result['booted'] == '1'
    result['awake'] = 'mWakefulness=Awake' in result['power']
    result['ac_powered'] = 'AC powered: true' in result['battery']
    result['resolution_ok'] = '320x640' in result['resolution']
    return result


def command(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return '无法读取'


def system():
    queries = {'power': ['/usr/bin/pmset', '-g', 'batt'],
               'sleep_settings': ['/usr/bin/pmset', '-g'],
               'assertions': ['/usr/bin/pmset', '-g', 'assertions'],
               'clamshell': ['/usr/sbin/ioreg', '-r', '-k', 'AppleClamshellState']}
    with ThreadPoolExecutor(max_workers=4) as pool:
        result = dict(zip(queries, pool.map(command, queries.values())))
    # Return only the relevant line, not the whole machine inventory.
    result['clamshell'] = next((line.strip() for line in result['clamshell'].splitlines()
                                if '"AppleClamshellState"' in line), '无法读取')
    result['on_ac'] = 'AC Power' in result['power']
    result['lock'] = '无法读取；锁屏本身不影响值守'
    task = nw.load_task()
    pid = task and task.get('pid')
    assertions = result['assertions']
    result['watch_caffeinate'] = bool(pid and (
        any(f'pid {pid}(' in line and 'PreventUserIdleSystemSleep' in line
            for line in assertions.splitlines()) or
        re.search(r'\bDetails:\s*caffeinate asserting\b[^\n]*'
                  + re.escape(f'(pid {pid})'), assertions)))
    started = time.monotonic()
    try:
        with socket.create_connection(('mobile.cmbchina.com', 443), timeout=3) as sock:
            with ssl.create_default_context().wrap_socket(sock, server_hostname='mobile.cmbchina.com'):
                pass
        result['network_s'] = round(time.monotonic() - started, 3)
        result['network_ok'] = result['network_s'] <= 1
    except (OSError, ssl.SSLError):
        result.update(network_ok=False, network_s=None)
    return result


def parser():
    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise nw.Abort('命令参数无效，请检查命令和必填参数。')
    p = Parser(description=__doc__)
    sub = p.add_subparsers(dest='cmd', required=True)
    for name in ('status', 'device', 'system', 'disarm', 'keep-awake', 'screenshot',
                 'set-login-pattern', 'set-payment-password', 'agent-release'):
        sub.add_parser(name)
    history = sub.add_parser('history')
    history.add_argument('--limit', type=int, default=0)
    log = sub.add_parser('log')
    log.add_argument('--lines', type=int, default=800)
    cancel = sub.add_parser('cancel')
    cancel.add_argument('--amount', default='0.01')
    cancel.add_argument('--limit', type=int, default=0)
    cancel.add_argument('--dry-run', action='store_true')
    cancel.add_argument('--list', action='store_true')
    cancel.add_argument('--yes', action='store_true')
    settings = sub.add_parser('settings')
    for key in purchase_settings.DEFAULTS:
        settings.add_argument('--' + key.replace('_', '-'), type=int)
    buy = sub.add_parser('buy')
    buy.add_argument('--code', required=True)
    buy.add_argument('--amount', required=True)
    buy_mode = buy.add_mutually_exclusive_group()
    buy_mode.add_argument('--dry-run', action='store_true')
    buy_mode.add_argument('--confirm-real-payment', action='store_true')
    emulator = sub.add_parser('emulator')
    emulator.add_argument('action', choices=['start', 'stop'])
    arm = sub.add_parser('arm')
    arm.add_argument('--code', required=True)
    arm.add_argument('--amount', required=True)
    when = arm.add_mutually_exclusive_group(required=True)
    when.add_argument('--at')
    when.add_argument('--now', action='store_true')
    arm.add_argument('--dry-run', action='store_true')
    arm.add_argument('--confirm-real-payment', action='store_true')
    arm.add_argument('--prep-minutes', type=int)
    arm.add_argument('--settings-revision')
    arm.add_argument('--mode', choices=nw.MODES, default='first_launch')
    arm.add_argument('--window-minutes', type=int)
    arm.add_argument('--until')
    resume = sub.add_parser('resume')
    resume.add_argument('--reason', required=True)
    resume.add_argument('--kill-stale', action='store_true')
    resume.add_argument('--after-manual-login', action='store_true')
    resume.add_argument('--session')
    heartbeat = sub.add_parser('agent-heartbeat')
    heartbeat.add_argument('--session', required=True)
    heartbeat.add_argument('--interval', type=int, required=True)
    saved = sub.add_parser('favorites')
    saved.add_argument('--list', action='store_true')
    saved.add_argument('--add')
    saved.add_argument('--title')
    saved.add_argument('--remove')
    saved.add_argument('--set-test', metavar='CODE')
    saved.add_argument('--test-amount')
    saved.add_argument('--clear-test', action='store_true')
    saved.add_argument('--test', action='store_true')
    return p


def dispatch(a):
    if a.cmd == 'settings':
        updates = {key: getattr(a, key) for key in purchase_settings.DEFAULTS
                   if getattr(a, key) is not None}
        with nw.task_lock(False):
            values = purchase_settings.load()
            if updates:
                values = purchase_settings.save(dict(values, **updates))
        return {'settings': values, 'settings_revision': purchase_settings.revision(values)}
    if a.cmd == 'status': return status()
    if a.cmd == 'favorites':
        if a.add is not None:
            return {'favorites': favorites.add(a.add, a.title or ''),
                    'test_item': favorites.test_item()}
        if a.remove is not None:
            return {'favorites': favorites.remove(a.remove),
                    'test_item': favorites.test_item()}
        if a.set_test is not None:
            if a.test_amount is None:
                raise nw.Abort('设置测试项需要同时给出 --test-amount。')
            return {'favorites': favorites.set_test(a.set_test, a.test_amount),
                    'test_item': favorites.test_item()}
        if a.clear_test:
            return {'favorites': favorites.clear_test(), 'test_item': None}
        if a.test:
            return {'test_item': favorites.test_item()}
        return {'favorites': favorites.load(), 'test_item': favorites.test_item()}
    if a.cmd == 'device': return device()
    if a.cmd == 'system': return system()
    if a.cmd == 'history':
        if not 0 <= a.limit <= 1000:
            raise nw.Abort('历史记录条数须为 0–1000（0 表示全部）。')
        path = nw.STATE / 'history.jsonl'
        rows = []
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines() if path.exists() else []:
            try: rows.append(json.loads(line))
            except ValueError: continue
        bounded = rows[-1000:]
        records = (bounded if a.limit == 0 else bounded[-a.limit:])[::-1]
        return {'records': records, 'total': len(rows), 'shown': len(records),
                'log_path': str(nw.LOG)}
    if a.cmd == 'log':
        if not 1 <= a.lines <= 5000:
            raise nw.Abort('日志行数须为 1–5000。')
        text = nw.LOG.read_text(encoding='utf-8', errors='replace') if nw.LOG.exists() else ''
        lines = text.splitlines()
        return {'path': str(nw.LOG), 'lines': lines[-a.lines:], 'total': len(lines),
                'exists': nw.LOG.exists()}
    if a.cmd == 'arm':
        if a.now and not a.dry_run and not a.confirm_real_payment:
            raise nw.Abort('立即真实布防必须明确确认实际付款。')
        return {'task': nw.arm_task(a.code, a.amount, a.at, a.dry_run, a.prep_minutes, a.now,
                                    mode=a.mode, window_minutes=a.window_minutes, until=a.until,
                                    settings_revision=a.settings_revision)}
    if a.cmd == 'disarm': return {'task': nw.disarm_task()}
    if a.cmd == 'resume':
        return {'task': nw.resume_task(a.reason, 'agent:' + a.session if a.session else 'user',
                                      a.kill_stale, a.after_manual_login)}
    if a.cmd == 'keep-awake':
        nw.keep_screen_on()
        return {}
    if a.cmd == 'screenshot':
        subprocess.run([str(nw.ROOT / 'scripts/capture')], capture_output=True, timeout=15, check=True)
        return {'path': str(nw.ROOT / 'var/screenshots/current.png')}
    if a.cmd == 'cancel':
        if not 0 <= a.limit <= 100:
            raise nw.Abort('撤单数量须为 0–100。')
        if not (a.list or a.dry_run) and not a.yes:
            raise nw.Abort('真实撤单需要明确确认。')
        amount = nw.fast_buy.parse_amount(a.amount)
        with nw.task_lock(False):
            task = nw.load_task()
            if task and (task.get('phase') in ('armed', 'preparing', 'waiting', 'firing') or nw.alive(task.get('pid'))):
                raise nw.Abort('值守任务活动期间不能撤单；先取消防守。')
            args = [sys.executable, '-B', str(nw.ROOT / 'src/cancel_orders.py'), '--amount', amount]
            if a.limit:
                args += ['--limit', str(a.limit)]
            if a.list:
                args.append('--list')
            elif a.dry_run:
                args.append('--dry-run')
            try:
                proc = subprocess.run(args, capture_output=True, text=True, timeout=240, cwd=str(nw.ROOT))
            except subprocess.TimeoutExpired:
                raise nw.Abort('撤单命令超时；请先查交易记录，勿重复操作。')
            output = proc.stdout.splitlines()
            if proc.returncode != 0:
                details = [line for line in (proc.stderr or '').splitlines() if line.strip()]
                message = details[-1] if details else (output[-1] if output else '撤单命令失败。')
                raise nw.Abort(message[:300])
            return {'output': output}
    if a.cmd == 'buy':
        if not a.dry_run and not a.confirm_real_payment:
            raise nw.Abort('真实单笔购买必须明确确认实际付款。')
        if not re.fullmatch(r'[A-Za-z0-9]{4,20}', a.code):
            raise nw.Abort('产品代码格式不正确。')
        amount = nw.fast_buy.parse_amount(a.amount)
        with nw.task_lock(False):
            task = nw.load_task()
            if task and (task.get('phase') in ('armed', 'preparing', 'waiting', 'firing') or nw.alive(task.get('pid'))):
                raise nw.Abort('值守任务活动期间不能单笔购买或演练。')
            import fast_buy_uia2
            settings = purchase_settings.load()
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                result = fast_buy_uia2.run(a.code, amount, dry_run=a.dry_run,
                                  form_deadline=settings[
                                      'drill_form_deadline' if a.dry_run else 'reopen_deadline'],
                                  settings=settings)
        return {'output': buffer.getvalue().splitlines(), 'result': result}
    if a.cmd.startswith('set-'):
        with nw.task_lock(False):
            task = nw.load_task()
            if task and task.get('phase') in ('preparing', 'waiting', 'firing'):
                raise nw.Abort('准备、抢购或提交期间不能修改凭据。')
            try:
                data = json.loads(sys.stdin.read(4097))
                if not isinstance(data, dict): raise ValueError()
                if not isinstance(data.get('new'), str): raise ValueError()
                if a.cmd == 'set-login-pattern': keychain_store.set_login_pattern(data['new'])
                else:
                    if not isinstance(data.get('current'), str): raise ValueError()
                    keychain_store.set_payment_password(data['new'], data['current'])
            except (ValueError, TypeError, KeyError):
                raise nw.Abort('凭据输入格式无效。')
        return {}
    if a.cmd == 'emulator':
        with nw.task_lock(False):
            task = nw.load_task()
            if a.action == 'stop':
                if task and task.get('phase') in ('armed', 'preparing', 'waiting', 'firing'):
                    raise nw.Abort('值守期间不能关闭模拟器。')
                manage.stop()
            else:
                if not nw.emulator_running(): manage.start()
                end = time.monotonic() + 45
                while not nw.booted():
                    if time.monotonic() >= end: raise nw.Abort('模拟器启动中，请稍后刷新。')
                    time.sleep(1)
                nw.keep_screen_on()
        return {}
    if a.cmd in ('agent-heartbeat', 'agent-release'):
        with nw.task_lock(False):
            path = nw.STATE / 'agent.json'
            if a.cmd == 'agent-release':
                path.unlink(missing_ok=True)
                return {}
            task = nw.load_task()
            if not task: raise nw.Abort('没有当前任务。')
            if not 30 <= a.interval <= 3600 or not 1 <= len(a.session) <= 100:
                raise nw.Abort('心跳间隔须为 30–3600 秒，会话名须为 1–100 字。')
            previous = agent_info(task)
            now = datetime.now().isoformat()
            data = {'session': a.session, 'interval_s': a.interval, 'last_seen': now,
                    'armed_at': task['armed_at'], 'started_at': previous.get('started_at', now)
                    if previous.get('session') == a.session else now}
            atomic_json(path, data)
            return {'agent': agent_info(task)}
    raise nw.Abort('未知命令。')


def main(argv=None):
    try:
        with redirect_stdout(io.StringIO()):
            a = parser().parse_args(argv)
            result = dispatch(a)
        payload, code = dict(result, ok=True), 0
    except (nw.Abort, nw.fast_buy.Stop, RuntimeError) as exc:
        payload, code = {'ok': False, 'error': str(exc)}, 1
    except Exception:
        payload, code = {'ok': False, 'error': '操作失败，请检查本机环境或输入格式。'}, 1
    print(json.dumps(payload, ensure_ascii=False))
    return code


if __name__ == '__main__':
    sys.exit(main())
