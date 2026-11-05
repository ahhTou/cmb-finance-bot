"""Convert a purchase password in the verified bank process and confirm at most once."""
import asyncio
from contextlib import ExitStack, contextmanager
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time

import fast_buy
import query_gate
import risk_confirm
from secure_input import BASE

RUNTIME = Path(__file__).resolve().parents[1] / 'var/native-password'
AGENT_SOURCE = Path(__file__).with_name('native_password_agent.js')
PAGE_SOURCE = Path(__file__).with_name('native_password_page.js')
APP_DIGEST = '83959ebc9a9cad18d52206bf3383544a271d84b690971ef35bb8de7799e9763e'
SERVER_DIGEST = '7bb6219131819c11e5fe53b3e32fae0b8d1ff4c2a9c35c1a549d2703ea0f3b9b'
FRIDA_VERSION = '17.25.2'


def require_runtime():
    try:
        manifest = json.loads((RUNTIME / 'manifest.json').read_text())
        if manifest['source_sha256'] != hashlib.sha256(AGENT_SOURCE.read_bytes()).hexdigest():
            raise ValueError('agent source changed')
        if not all((RUNTIME / name).exists() for name in ('frida-server', 'agent.js', 'python/frida')):
            raise ValueError('runtime incomplete')
    except (OSError, ValueError, KeyError, TypeError):
        raise fast_buy.Stop('无键盘组件未安装或需要更新，请运行 scripts/setup-native-password 后再试。') from None


def verify_app():
    """The bridge uses private class layouts tied to the tested bank build."""
    try:
        paths = fast_buy.adb('shell', 'pm', 'path', 'cmb.pb').splitlines()
        if len(paths) != 1 or not re.fullmatch(r'package:/data/app/[\w/=.~-]+/base\.apk', paths[0]):
            raise ValueError('unexpected APK layout')
        digest = fast_buy.adb('shell', 'sha256sum', paths[0][len('package:'):]).split()[0]
        if digest != APP_DIGEST:
            raise ValueError('unverified version')
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        raise fast_buy.Stop('当前招行 App 版本未验证无键盘输入。请在设置中开启「模拟密码输入」后再操作。') from None


def _load_frida():
    require_runtime()
    sys.path.insert(0, str(RUNTIME / 'python'))
    try:
        import frida
        if frida.__version__ != FRIDA_VERSION:
            raise ImportError('Frida version mismatch')
        return frida
    except (ImportError, OSError):
        raise fast_buy.Stop('无键盘组件无法加载，请重新运行 scripts/setup-native-password。') from None
    finally:
        sys.path.pop(0)


@contextmanager
def _deadline(frida, seconds):
    cancellable = frida.Cancellable()
    timer = threading.Timer(seconds, cancellable.cancel)
    timer.daemon = True
    timer.start()
    try:
        with cancellable:
            yield
    finally:
        timer.cancel()


def _try_adb(*args):
    try:
        fast_buy.adb(*args)
    except (OSError, subprocess.SubprocessError):
        pass


def _stop_server(server, remote, name):
    # The unique basename and executable path identify only this invocation.
    _try_adb('shell', 'su', '0', 'sh', '-c',
             f"'for p in $(pidof {name}); do "
             f'[ "$(readlink /proc/$p/exe)" = {remote} ] && kill "$p"; '
             f"done; rm -f {remote}'")
    if server and server.poll() is None:
        server.terminate()
        try:
            server.wait(timeout=2)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()


@contextmanager
def _agent(frida, config):
    """Create an authenticated loopback transport owned by this purchase only."""
    local_server = RUNTIME / 'frida-server'
    with local_server.open('rb') as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != SERVER_DIGEST:
        raise fast_buy.Stop('无键盘组件校验失败，请重新安装。')
    forwards = fast_buy.adb('forward', '--list')
    matches = re.findall(r'^emulator-15554 tcp:9222 localabstract:webview_devtools_remote_(\d+)\s*$',
                         forwards, re.M)
    if len(matches) != 1:
        raise fast_buy.Stop('无法确定购买页所属的招行进程。')
    pid = int(matches[0])
    name = 'cmbpw-' + secrets.token_hex(4)
    remote = '/data/local/tmp/' + name
    remote_port = 30000 + secrets.randbelow(20000)
    token = secrets.token_hex(32)
    manager = frida.get_device_manager()
    server = None
    with ExitStack() as stack:
        stack.callback(lambda: _stop_server(server, remote, name))
        fast_buy.adb('push', str(local_server), remote)
        fast_buy.adb('shell', 'chmod', '700', remote)
        server = subprocess.Popen([*BASE, 'shell', 'su', '0', 'timeout', '60', remote,
                                   '-l', f'127.0.0.1:{remote_port}', '--token', token],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
        port = fast_buy.adb('forward', 'tcp:0', f'tcp:{remote_port}').strip()
        if not port.isdecimal():
            raise fast_buy.Stop('无键盘组件未能建立本机连接。')
        stack.callback(_try_adb, 'forward', '--remove', f'tcp:{port}')
        address = f'127.0.0.1:{port}'
        with _deadline(frida, 5):
            device = manager.add_remote_device(address, token=token)
            stack.callback(_frida_cleanup, frida, manager.remove_remote_device, address)
            # Wait for the newly started listener before attempting a single attach.
            until = time.monotonic() + 3
            while True:
                try:
                    device.enumerate_processes()
                    break
                except (frida.ServerNotRunningError, frida.TransportError):
                    if time.monotonic() >= until or server.poll() is not None:
                        raise
                    time.sleep(.05)
        with _deadline(frida, 12):
            session = device.attach(pid)
            stack.callback(_frida_cleanup, frida, session.detach)
        with _deadline(frida, 5):
            source = (RUNTIME / 'agent.js').read_text().replace('__CMB_PASSWORD_CONFIG__', json.dumps(config))
            script = session.create_script(source)
            ready, captured, failed = threading.Event(), threading.Event(), threading.Event()

            def receive(message, _data):
                stage = (message.get('payload') or {}).get('stage') if message.get('type') == 'send' else None
                if stage == 'ready':
                    ready.set()
                elif stage == 'captured':
                    captured.set()
                elif stage in ('rejected', 'capture_failed') or message.get('type') == 'error':
                    failed.set()
                    ready.set()
                    captured.set()

            script.on('message', receive)
            script.load()
        if not ready.wait(4) or failed.is_set():
            raise fast_buy.Stop('无键盘组件未能连接当前购买页。')
        yield script, captured, failed


def _frida_cleanup(frida, action, *args):
    try:
        with _deadline(frida, 2):
            action(*args)
    except Exception:
        pass


async def _page_call(page, expression):
    import websockets
    async with websockets.connect(page['webSocketDebuggerUrl'], open_timeout=1) as ws:
        return await query_gate.Client(ws).evaluate(expression)


async def _find_page(code, amount, page):
    candidates = [page] if page is not None else query_gate.pages()
    matches = [p for p in candidates if risk_confirm.candidate(p, code, amount)
               and await _page_call(p, risk_confirm.VISIBLE_FORM)]
    if len(matches) != 1:
        raise fast_buy.Stop('无法唯一确认前台目标购买表单。')
    return matches[0]


def run(code, amount, password, *, dry_run, page, before_submit, mark, wait_result):
    frida = _load_frida()
    verify_app()
    page = asyncio.run(_find_page(code, amount, page))
    config = {'code': code, 'amount': amount, 'token': secrets.token_hex(16), 'dryRun': dry_run}
    token = json.dumps(config['token'])
    attempted = False
    installed = False

    def evaluate(expression):
        return asyncio.run(_page_call(page, expression))

    def meta():
        return evaluate(f'window.__cmbOnePurchase?.meta({token})')

    try:
        guard = PAGE_SOURCE.read_text().replace('__CMB_PASSWORD_CONFIG__', json.dumps(config))
        installed = evaluate(guard) is True
        if not installed:
            raise fast_buy.Stop('当前购买分支不支持无键盘输入，未提交。')
        with _agent(frida, config) as (script, captured, failed):
            risk_confirm.run(code, amount, mark=mark, page=page)
            if not captured.wait(4) or failed.is_set():
                raise fast_buy.Stop('无法确认原生密码请求，未提交。')
            if mark:
                mark('password', time.monotonic())
            if not (meta() or {}).get('validModal'):
                raise fast_buy.Stop('密码面板或金额校验失败，未提交。')
            # Only fixed metadata crosses back to the host. Ciphertext stays in the App.
            with _deadline(frida, 5):
                check = script.exports_sync.check()
                if check != {'factorMode': 1, 'packingMode': 0,
                             'nativeState': True, 'sessionUnchanged': True}:
                    raise fast_buy.Stop('密码组件的模式或会话发生变化，未提交。')
                converted = script.exports_sync.stage(password)
                password = None
            if (converted.get('requests'), converted.get('mode'), converted.get('packingMode'),
                    converted.get('inputLength')) != (1, 1, 0, 6):
                raise fast_buy.Stop('无键盘密码转换未通过校验，未提交。')
            until = time.monotonic() + 2
            while not (meta() or {}).get('ready'):
                if time.monotonic() >= until:
                    raise fast_buy.Stop('密码面板没有收到有效的转换结果，未提交。')
                time.sleep(.04)
            if dry_run:
                if mark:
                    mark('typed', time.monotonic())
                print('演练：已在招行组件内转换密码，未点确定、未提交。', flush=True)
                return None
            if before_submit:
                before_submit()
            attempted = True
            try:
                evaluate(f'window.__cmbOnePurchase?.commit({token})')
            except Exception:
                pass  # The confirmation might already have run. Read results only.
            if mark:
                mark('submit', time.monotonic())
        result = _read_result(meta, wait_result, mark)
        print(f'结果页提示：{result}', flush=True)
        return result
    except fast_buy.Stop:
        raise
    except Exception as exc:
        # Do not include raw Frida, ADB or page exception messages in logs.
        print(f'无键盘流程中止（{type(exc).__name__}）', flush=True)
        raise fast_buy.Stop('提交结果未知，请查交易记录。' if attempted
                            else '无键盘密码输入失败，未提交。') from None
    finally:
        password = None
        if installed and not attempted:
            try:
                evaluate(f'window.__cmbOnePurchase?.discard({token})')
            except Exception:
                pass


def _read_result(meta, wait_result, mark):
    end = time.monotonic() + 20
    accepted = False
    while time.monotonic() < end:
        try:
            reply = meta()
        except Exception:
            reply = None
        if reply and reply.get('received'):
            accepted = reply.get('accepted') is True
            if not accepted:
                rejection = reply.get('rejection') or {}
                reason = ' '.join(part for part in (rejection.get('code'), rejection.get('category')) if part)
                if mark:
                    mark('result', time.monotonic())
                return f'银行未受理：{reason}' if reason else '银行未受理'
        try:
            result = wait_result(timeout=.4)
            if mark:
                mark('result', time.monotonic())
            return result
        except fast_buy.Stop:
            pass
    return '银行已受理，结果页未识别' if accepted else '结果未知，请查交易记录'
