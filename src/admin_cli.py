#!/usr/bin/env python3
"""JSON bridge for the local management app. No credentials in argv or errors."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime
import io
import json
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import time

import night_watch as nw
import keychain_store
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
                mail_configured=notify.configured())
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
    result['watch_caffeinate'] = bool(pid and any(f'pid {pid}(' in line and
        'PreventUserIdleSystemSleep' in line for line in result['assertions'].splitlines()))
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
    for name in ('status', 'device', 'system', 'history', 'disarm', 'keep-awake', 'screenshot',
                 'set-login-pattern', 'set-payment-password', 'agent-release'):
        sub.add_parser(name)
    emulator = sub.add_parser('emulator')
    emulator.add_argument('action', choices=['start', 'stop'])
    arm = sub.add_parser('arm')
    arm.add_argument('--code', required=True)
    arm.add_argument('--amount', required=True)
    when = arm.add_mutually_exclusive_group(required=True)
    when.add_argument('--at')
    when.add_argument('--now', action='store_true')
    arm.add_argument('--dry-run', action='store_true')
    arm.add_argument('--prep-minutes', type=int, default=15)
    resume = sub.add_parser('resume')
    resume.add_argument('--reason', required=True)
    resume.add_argument('--kill-stale', action='store_true')
    resume.add_argument('--after-manual-login', action='store_true')
    resume.add_argument('--session')
    heartbeat = sub.add_parser('agent-heartbeat')
    heartbeat.add_argument('--session', required=True)
    heartbeat.add_argument('--interval', type=int, required=True)
    return p


def dispatch(a):
    if a.cmd == 'status': return status()
    if a.cmd == 'device': return device()
    if a.cmd == 'system': return system()
    if a.cmd == 'history':
        path = nw.STATE / 'history.jsonl'
        rows = []
        for line in path.read_text().splitlines() if path.exists() else []:
            try: rows.append(json.loads(line))
            except ValueError: continue
        return {'records': rows[-20:][::-1]}
    if a.cmd == 'arm':
        if a.now and not a.dry_run:
            raise nw.Abort('立即排练必须勾选演练。')
        return {'task': nw.arm_task(a.code, a.amount, a.at, a.dry_run, a.prep_minutes, a.now)}
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
    if a.cmd.startswith('set-'):
        with nw.task_lock(False):
            task = nw.load_task()
            if task and task.get('phase') in ('preparing', 'firing'):
                raise nw.Abort('准备或提交期间不能修改凭据。')
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
                if task and task.get('phase') in ('armed', 'preparing', 'firing'):
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
