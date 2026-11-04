"""Use the original risk component handlers, then stop at the native password UI.

Does not load credentials or invoke doBuy. There is no click/retry fallback once
preAmountExam starts, since repeating a half-completed confirmation is unsafe.
"""
import asyncio
import json
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import fast_buy
from query_gate import Client, pages

SCRIPT = Path(__file__).with_suffix('.js')


def candidate(page, code, amount):
    url = urlparse(page.get('url', ''))
    query = parse_qs(url.query)
    try:
        desc = json.loads(page.get('description') or '{}')
        return (url.hostname == 'mobile.cmbchina.com' and url.path.endswith('/saentrustbuy.html')
                and query.get('CodeInn') == [code] and query.get('FndInn') == [code]
                and Decimal((query.get('CurDepositBuyAmount') or [''])[0]) == Decimal(amount)
                and desc.get('visible') and 0 <= desc.get('screenY', -1) <= 100
                and (desc.get('width') or 0) >= 300 and (desc.get('height') or 0) >= 500)
    except (ValueError, InvalidOperation, TypeError):
        return False


VISIBLE_FORM = """(()=>{
 const root=document.querySelector('#app')?.__vue__;let view;
 (function walk(v,d){if(!v||d>20)return;if(v.ordInfo&&typeof v.preAmountExam==='function')view=v;
  (v.$children||[]).forEach(c=>walk(c,d+1));})(root,0);
 return !!view&&view.viewType==='A'&&!document.hidden;
})()"""


async def confirm(code, amount, timeout=10):
    import websockets
    matches = []
    for page in pages():
        if not candidate(page, code, amount):
            continue
        async with websockets.connect(page['webSocketDebuggerUrl'], open_timeout=1) as ws:
            if await Client(ws).evaluate(VISIBLE_FORM):
                matches.append(page)
    if len(matches) != 1:
        raise fast_buy.Stop('无法唯一确认前台目标购买表单，未启动风险确认。')
    token = uuid.uuid4().hex
    config = dict(code=code, amount=amount, token=token, timeoutMs=int(timeout*1000))
    source = SCRIPT.read_text().replace('__CONFIG__', json.dumps(config))
    async with websockets.connect(matches[0]['webSocketDebuggerUrl'], open_timeout=1) as ws:
        client = Client(ws)
        began = time.monotonic()
        try:
            started = await client.evaluate(source)
            if not started or not started.get('started'):
                raise fast_buy.Stop('购买页状态或协议/资金确认分支不支持 JS 快速确认，已停止。')
            end = began + timeout + 1
            while time.monotonic() < end:
                state = await client.evaluate("""(()=>{const s=window.__cmbRiskConfirm;
                    if(s)s.keepAlive(__TOKEN__);return s?{
                    token:s.token,status:s.status,reason:s.reason,events:s.events,
                    passwordCalls:s.passwordCalls,textMatches:s.textMatches}:null})()""".replace("__TOKEN__", json.dumps(token)))
                if not state or state['token'] != token:
                    raise fast_buy.Stop('风险确认页面状态已丢失，已停止，不重试。')
                if state['status'] == 'password_requested':
                    if state['passwordCalls'] != 1 or not state.get('textMatches'):
                        raise fast_buy.Stop('风险确认结果不一致，已停止。')
                    return state, began
                if state['status'] == 'stopped':
                    messages = {'bank_precheck_failed':'银行购买预检查或风险资料查询未通过',
                                'additional_protocol_confirmation':'页面需要额外协议确认',
                                'additional_funding_confirmation':'页面需要额外资金确认',
                                'risk_text_mismatch':'原组件风险文本校验未通过',
                                'document_hidden':'购买页已切到后台'}
                    raise fast_buy.Stop(messages.get(state.get('reason'), '风险组件确认未完成') + '，已停止，不重试。')
                await asyncio.sleep(.04)
            raise fast_buy.Stop('JS 风险确认超时，已停止，不重试。')
        finally:
            try:
                await client.evaluate(f'window.__cmbRiskConfirm?.cleanup({json.dumps(token)})')
            except Exception:
                pass


def run(code, amount, timeout=10, mark=None):
    state, began = asyncio.run(confirm(code, amount, timeout))
    names = {'next_handler':'next', 'risk_ready':'risk', 'quick_input':'fill', 'risk_confirm':'confirm'}
    for event in state['events']:
        if mark is not None and event['name'] in names:
            mark(names[event['name']], began+event['ms']/1000)
    print('JS 风险确认完成：原预检查、资料加载及文本校验通过，密码面板已请求。', flush=True)
