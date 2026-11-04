"""Read-only CDP evidence for a freshly opened purchase document.

Never returns page text or account data. A document's time origin distinguishes
reloads of the same URL; target IDs alone do not, because WebViews are reused.
"""
import asyncio
import json
import urllib.request
from urllib.parse import parse_qs, urlparse

ERRORS = ("购买失败", "额度不足", "TOPI", "系统繁忙", "网络异常", "请稍后再试")

SCRIPT = r"""(()=>{
 const text=document.body ? document.body.innerText : '';
 const errors=['购买失败','额度不足','TOPI','系统繁忙','网络异常','请稍后再试'];
 return {origin:performance.timeOrigin, url:location.href,
   ready:document.readyState==='complete',
   form:text.includes('可用余额') && text.includes('同意协议下一步'),
   error:errors.find(e=>text.includes(e))||'',
   hidden:document.visibilityState==='hidden'};
})()"""


def snapshot(timeout=0.8):
    """None means incomplete evidence; callers must never accept it as empty."""
    import websockets
    try:
        with urllib.request.urlopen('http://127.0.0.1:9222/json', timeout=timeout) as r:
            pages = json.load(r)

        async def read(page):
            desc = json.loads(page.get('description') or '{}')
            # A suspended background WebView can hang CDP indefinitely. Record
            # its ID without evaluating it, so it cannot become a fresh form
            # merely by moving to the foreground.
            if (desc.get('width') or 0) < 300 or (desc.get('height') or 0) < 500:
                return dict(id=page['id'], origin=None, front=False)
            if not desc.get('visible') or not 0 <= desc.get('screenY', -1) <= 100:
                return dict(id=page['id'], origin=None, front=False)
            async with websockets.connect(page['webSocketDebuggerUrl'],
                                          open_timeout=timeout, close_timeout=0.1) as ws:
                await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate',
                                          'params': {'expression': SCRIPT, 'returnByValue': True}}))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get('id') == 1:
                        value = msg.get('result', {}).get('result', {}).get('value')
                        if not isinstance(value, dict) or not value.get('origin'):
                            raise ValueError('No document identity')
                        value['id'] = page['id']
                        value['front'] = (bool(desc.get('visible'))
                                          and 0 <= desc.get('screenY', -1) <= 100
                                          and not value['hidden'])
                        return value

        async def collect():
            return await asyncio.wait_for(asyncio.gather(*(read(p) for p in pages)), timeout)

        return [p for p in asyncio.run(collect()) if p is not None]
    except Exception:
        return None


def identity(page):
    return page['id'], page['origin']


def outcome(pages, baseline, code, amount):
    """Only one fresh, frontmost document with a completed business view counts."""
    if pages is None:
        return ''
    fresh = [p for p in pages if p['front'] and identity(p) not in baseline
             and (p['id'], None) not in baseline]
    if len(fresh) != 1:
        return ''
    page = fresh[0]
    url = urlparse(page['url'])
    if not page['ready'] or url.hostname != 'mobile.cmbchina.com':
        return ''
    query = parse_qs(url.query)
    if url.path.endswith('/saentrustbuy.html'):
        from decimal import Decimal, InvalidOperation
        try:
            matches = ((query.get('CodeInn') or [''])[0] == code
                       and (query.get('FndInn') or [''])[0] == code
                       and Decimal((query.get('CurDepositBuyAmount') or [''])[0]) == Decimal(amount))
        except InvalidOperation:
            matches = False
        if not matches:
            return ''
        if page['error']:
            return page['error']
        if page['form']:
            return 'form'
    elif url.path.endswith('/sfoveramount.html') and page['error']:
        return page['error']
    return ''
