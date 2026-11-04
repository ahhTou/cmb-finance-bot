"""Prepare one isolated purchase WebView, gate its own queryBuy, then poll it.

All repeated requests use the unmodified page API with the original arguments.
This module never invokes next-step, credentials, or submission methods.
"""
import asyncio
import json
import time
import urllib.request
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import fast_buy
import purchase_settings

SCRIPT = Path(__file__).with_suffix('.js')
FLOW = 'query_gate_v1'
REQUEST_TIMEOUT_MS = 10000
LEASE_MS = 15000
STAGING_URL = 'https://mobile.cmbchina.com/IEntrustFinance/subsidiaryfinancing/sfoveramount.html'


def schedule(when, mode, settings):
    settings = purchase_settings.validate(settings)
    delta = (settings['first_offset_ms'] if mode == 'first_launch'
             else -settings['irregular_advance_ms'])
    start = when + timedelta(milliseconds=delta)
    end = (start + timedelta(minutes=settings['irregular_window_minutes'])
           if mode == 'redemption' else
           start + timedelta(milliseconds=(settings['first_max_retries'] + 1) * REQUEST_TIMEOUT_MS,
                             seconds=30))
    return start, end


def backoff(settings):
    """Redemption retry tiers for query_gate.js, offsets from the planned first query."""
    return dict(burstMs=settings['irregular_burst_seconds'] * 1000,
                rampMs=settings['irregular_ramp_seconds'] * 1000,
                idleMs=settings['irregular_idle_after_seconds'] * 1000,
                burst=[settings['irregular_retry_min_ms'], settings['irregular_retry_max_ms']],
                slow=[settings['irregular_slow_min_ms'], settings['irregular_slow_max_ms']],
                idle=[settings['irregular_idle_min_ms'], settings['irregular_idle_max_ms']])


def pages():
    with urllib.request.urlopen('http://127.0.0.1:9222/json', timeout=1) as response:
        return json.load(response)


class Client:
    def __init__(self, ws):
        self.ws = ws
        self.sequence = 0

    async def call(self, method, params=None):
        self.sequence += 1
        call_id = self.sequence
        await self.ws.send(json.dumps(dict(id=call_id, method=method, params=params or {})))
        while True:
            message = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=3))
            if message.get('method') == 'Fetch.requestPaused':
                # During bootstrap this guard catches changed bank code that
                # bypasses our wrapper. Fail the request before it is sent.
                self.sequence += 1
                await self.ws.send(json.dumps(dict(id=self.sequence, method='Fetch.failRequest',
                    params={'requestId': message['params']['requestId'], 'errorReason': 'Aborted'})))
                raise fast_buy.Stop('购买页拦截未就绪，已阻止提前 queryBuy，未提交。')
            if message.get('id') == call_id:
                if message.get('error'):
                    raise fast_buy.Stop('CDP 操作失败，停止购买页等待。')
                return message.get('result', {})

    async def evaluate(self, expression):
        result = await self.call('Runtime.evaluate', dict(expression=expression, returnByValue=True))
        if result.get('exceptionDetails'):
            raise fast_buy.Stop('购买页脚本执行失败，已停止。')
        return result.get('result', {}).get('value')


async def blank_target():
    """Create an isolated native container on the inert quota-result page first."""
    existing = {p['id'] for p in pages()}
    fast_buy.adb('shell', 'am', 'start', '-a', 'android.intent.action.VIEW',
                 '-d', "'" + fast_buy.app_link(STAGING_URL) + "'", 'cmb.pb')
    end = time.monotonic() + 10
    while time.monotonic() < end:
        new = []
        for page in pages():
            if page['id'] in existing or urlparse(page.get('url', '')).path != urlparse(STAGING_URL).path:
                continue
            desc = json.loads(page.get('description') or '{}')
            if desc.get('visible') and (desc.get('width') or 0) >= 300 and (desc.get('height') or 0) >= 500:
                new.append(page)
        if len(new) == 1:
            return new[0]
        if len(new) > 1:
            raise fast_buy.Stop('新建购买容器不唯一，已停止。')
        await asyncio.sleep(.1)
    raise fast_buy.Stop('未能打开隔离的购买过渡容器；未打开购买页、未发送 queryBuy。')


READ_STATE = r"""(()=>{
 const s=window.__cmbQueryGate;
 if(!s)return null;
 const el=document.querySelector('#app');let view=null;
 (function walk(v,d){if(!v||d>15||view)return;
   if(v.ordInfo&&typeof v.queryBuy==='function')view=v;
   (v.$children||[]).forEach(c=>walk(c,d+1));})(el&&el.__vue__,0);
 const text=document.body?document.body.innerText:'';
 return {token:s.token,code:s.code,installed:s.installed,heldCalls:s.heldCalls,
   attempts:s.attempts,status:s.status,reason:s.reason,quota:s.quota,
   origin:performance.timeOrigin,url:location.href,hidden:document.hidden,
   form:!!view&&view.viewType==='A'&&text.includes('可用余额')&&text.includes('同意协议下一步')};
})()"""


async def watch(task, heartbeat, prepared=None, *, stop_after_held=False):
    """Return (native form, raw product quota). stop_after_held is read-only QA."""
    import websockets
    import fast_buy_uia2 as fu
    fast_buy.ensure_forward()
    start = datetime.fromisoformat(task['fire_at'])
    end = datetime.fromisoformat(task['end_at'])
    settings = purchase_settings.validate(task['watch_settings'])
    target = await blank_target()
    token = uuid.uuid4().hex
    async with websockets.connect(target['webSocketDebuggerUrl'], open_timeout=2, close_timeout=.2) as ws:
        client = Client(ws)
        # Calibrate device wall clock using the midpoint of a CDP round trip.
        t0 = time.time() * 1000
        device_now = await client.evaluate('Date.now()')
        offset = device_now - (t0 + time.time() * 1000) / 2
        config = dict(token=token, code=task['code'], mode=task['mode'],
                      startAt=start.timestamp()*1000 + offset,
                      endAt=end.timestamp()*1000 + offset,
                      maxAttempts=settings['first_max_retries'] + 1,
                      retryMinMs=settings['irregular_retry_min_ms'],
                      retryMaxMs=settings['irregular_retry_max_ms'],
                      backoff=backoff(settings),
                      requestTimeoutMs=REQUEST_TIMEOUT_MS, leaseMs=LEASE_MS)
        script = SCRIPT.read_text().replace('__CONFIG__', json.dumps(config))
        await client.call('Page.enable')
        await client.call('Fetch.enable', {'patterns': [
            {'urlPattern': '*querybuy*', 'requestStage': 'Request'},
            {'urlPattern': '*queryBuy*', 'requestStage': 'Request'}]})
        preload = await client.call('Page.addScriptToEvaluateOnNewDocument', {'source': script})
        origin = None
        succeeded = False
        try:
            await client.call('Page.navigate', {'url': fast_buy.BUY_URL.format(code=task['code'], amount=task['amount'])})
            install_deadline = min(time.monotonic()+15, time.monotonic()+max(0,(start-datetime.now()).total_seconds()-1))
            while time.monotonic() < install_deadline:
                state = await client.evaluate(READ_STATE)
                if (state and state['token'] == token and state['installed']
                        and state['heldCalls'] > 0 and state['status'] == 'waiting'):
                    if state['attempts'] != 0:
                        raise fast_buy.Stop('queryBuy 在安装确认前已开始，任务停止。')
                    origin = state['origin']
                    task['query_gate_target'] = target['id']
                    task['query_gate_origin'] = origin
                    task['query_gate_token'] = token
                    break
                heartbeat(0)
                await asyncio.sleep(.05)
            if origin is None:
                raise fast_buy.Stop('未能在开始时间前确认 queryBuy 挂起，已停止。')
            # At this point the wrapper is verified, the original call is held,
            # and all bootstrap CDP events were drained before disabling guard.
            await client.call('Fetch.disable')
            if prepared:
                prepared()
            if stop_after_held:
                return state, None
            while datetime.now() < end:
                alive = await client.evaluate(f'window.__cmbQueryGate?.keepAlive({json.dumps(token)})')
                state = await client.evaluate(READ_STATE)
                if not alive or not state or state['token'] != token or state['origin'] != origin:
                    raise fast_buy.Stop('购买页状态丢失或已换页，未提交。')
                heartbeat(state['attempts'])
                if state['status'] == 'stopped':
                    reasons = {'attempts_exhausted':'首发查询次数已用完', 'window_expired':'查询窗口已结束',
                               'query_rejected':'银行查询拒绝，停止自动重试', 'query_failed':'查询失败或超时',
                               'watcher_lost':'值守连接已失效'}
                    raise fast_buy.Stop(reasons.get(state['reason'], '购买页查询已停止'))
                if state['status'] == 'ready' and state['form'] and not state['hidden']:
                    url = urlparse(state['url'])
                    query = parse_qs(url.query)
                    if (url.hostname != 'mobile.cmbchina.com' or not url.path.endswith('/saentrustbuy.html')
                            or query.get('CodeInn') != [task['code']]):
                        raise fast_buy.Stop('购买页产品校验失败。')
                    if task['mode'] == 'redemption' and datetime.now() >= end:
                        break
                    root = fu.dump()
                    text = ' '.join(fast_buy.label(n) for n in root.iter('node'))
                    if '可用余额' in text and '同意协议下一步' in text:
                        succeeded = True
                        return root, state['quota']
                delay = .5 if datetime.now() < start - timedelta(seconds=1) else .08
                await asyncio.sleep(delay)
            raise fast_buy.Stop('查询窗口已结束，未提交。')
        finally:
            try:
                if not succeeded:
                    await client.evaluate(f'window.__cmbQueryGate?.cancel({json.dumps(token)})')
                await client.call('Page.removeScriptToEvaluateOnNewDocument', {'identifier': preload['identifier']})
            except Exception:
                pass  # lease expiry still prevents background polling


def run(task, heartbeat, prepared=None):
    return asyncio.run(watch(task, heartbeat, prepared))


def verify_prepared(task):
    """Recheck the same front document immediately before the submit boundary."""
    import fast_buy_uia2 as fu
    matches = [p for p in pages() if p['id'] == task.get('query_gate_target')]
    if len(matches) != 1:
        raise fast_buy.Stop('原购买页已关闭，停止购买。')
    desc = json.loads(matches[0].get('description') or '{}')
    if not desc.get('visible') or not 0 <= desc.get('screenY', -1) <= 100:
        raise fast_buy.Stop('原购买页不在前台，停止购买。')

    async def check():
        import websockets
        async with websockets.connect(matches[0]['webSocketDebuggerUrl'], open_timeout=1) as ws:
            return await Client(ws).evaluate(READ_STATE)

    state = asyncio.run(check())
    url = urlparse(state['url']) if state else None
    query = parse_qs(url.query) if url else {}
    if (not state or state['token'] != task.get('query_gate_token')
            or state['origin'] != task.get('query_gate_origin') or not state['form']
            or state['hidden'] or state['status'] != 'ready'
            or url.hostname != 'mobile.cmbchina.com' or not url.path.endswith('/saentrustbuy.html')
            or query.get('CodeInn') != [task['code']]
            or query.get('CurDepositBuyAmount') != [task['amount']]):
        raise fast_buy.Stop('原购买页校验已失效，停止购买。')
    if task['mode'] == 'redemption' and datetime.now() >= datetime.fromisoformat(task['end_at']):
        raise fast_buy.Stop('查询窗口已结束，停止购买。')
    root = fu.dump()
    text = ' '.join(fast_buy.label(n) for n in root.iter('node'))
    if '可用余额' not in text or '同意协议下一步' not in text:
        raise fast_buy.Stop('原购买表单已变化，停止购买。')
    return root


def finish(task):
    """Best-effort overlay update; cannot create requests or transactions."""
    try:
        matches = [p for p in pages() if p['id'] == task.get('query_gate_target')]
        if not matches:
            return

        async def update():
            import websockets
            async with websockets.connect(matches[0]['webSocketDebuggerUrl'], open_timeout=1) as ws:
                token = json.dumps(task.get('query_gate_token'))
                await Client(ws).evaluate(f'window.__cmbQueryGate?.finish({token})')
        asyncio.run(update())
    except Exception:
        pass
