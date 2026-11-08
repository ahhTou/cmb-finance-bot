"""Saved product codes with a title, an optional test item and quota-time notes.

One row may be marked as the test item with an amount; drills use it as the
default product and amount instead of asking every time. At most one row is
the test item. Quota-time entries are reference notes for the account holder
and the Agent: they never drive a purchase, a watch task or a plan. The file
is 0600 and ignored by Git; entries are unique by case-insensitive code.
"""
import json
import re
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'var/favorites.json'
MAX_ITEMS = 100
MAX_QUOTA_TIMES = 50
CODE = re.compile(r'[A-Za-z0-9]{4,20}')
TITLE_MAX = 40
NOTE_MAX = 100
KINDS = ('issue', 'bargain', 'regular')
CLOCK = re.compile(r'([01]\d|2[0-3]):[0-5]\d')
DAY = re.compile(r'\d{4}-\d{2}-\d{2}')
QUOTA_ID = re.compile(r'[A-Za-z0-9_-]{1,24}')
# 额度数默认单位万；100 亿是个人理财场景下足够宽的上限。
QUOTA_MAX_WAN = Decimal(1_000_000)


def amount_text(value):
    """Validate a test amount and normalize it to 'N.NN'.

    There is no upper limit: the account owner is responsible for the amount.
    """
    try:
        amount = Decimal(str(value).replace(',', '').strip())
    except InvalidOperation:
        raise RuntimeError('测试金额格式不正确。')
    if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
        raise RuntimeError('测试金额必须是正数，最多两位小数。')
    return f'{amount:.2f}'


def quota_amount_text(value):
    """Validate a quota amount in 万 and normalize it without trailing zeros."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise RuntimeError('额度数量格式不正确。')
    try:
        amount = Decimal(str(value).replace(',', '').strip())
    except InvalidOperation:
        raise RuntimeError('额度数量格式不正确。')
    if not amount.is_finite() or amount <= 0 or amount > QUOTA_MAX_WAN \
            or amount.as_tuple().exponent < -2:
        raise RuntimeError('额度数量格式不正确。')
    return format(amount.normalize(), 'f')


def _title_text(value):
    title = value.strip() if isinstance(value, str) else ''
    if not 1 <= len(title) <= TITLE_MAX:
        raise RuntimeError('标题须为 1–40 个字符。')
    return title


def _kind_text(value):
    if value not in KINDS:
        raise RuntimeError('额度时间类型不正确。')
    return value


def _clock_text(value):
    if not isinstance(value, str) or not CLOCK.fullmatch(value):
        raise RuntimeError('额度时间格式不正确。')
    return value


def _day_text(value):
    if not isinstance(value, str) or not DAY.fullmatch(value):
        raise RuntimeError('额度日期格式不正确。')
    try:
        datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        raise RuntimeError('额度日期格式不正确。') from None
    return value


def _weekday_list(value):
    if not isinstance(value, list) or not value:
        raise RuntimeError('额度星期格式不正确。')
    days = set()
    for day in value:
        if type(day) is not int or not 1 <= day <= 7:
            raise RuntimeError('额度星期格式不正确。')
        days.add(day)
    return sorted(days)


def _note_text(value):
    if value is None:
        return ''
    if not isinstance(value, str):
        raise RuntimeError('备注格式不正确。')
    note = value.strip()
    if len(note) > NOTE_MAX:
        raise RuntimeError(f'备注最多 {NOTE_MAX} 个字符。')
    return note


def _quota_entry(raw, used_ids):
    """Validate one quota-time entry; the caller must supply unique ids."""
    if not isinstance(raw, dict):
        raise RuntimeError('额度时间格式不正确。')
    kind = _kind_text(raw.get('kind'))
    clock = _clock_text(raw.get('time'))
    entry = {'kind': kind}
    if kind == 'issue':
        entry['date'] = _day_text(raw.get('date'))
    else:
        entry['weekdays'] = _weekday_list(raw.get('weekdays'))
    entry['time'] = clock
    amount = raw.get('amount_wan')
    if amount is not None:
        entry['amount_wan'] = quota_amount_text(amount)
    note = _note_text(raw.get('note'))
    if note:
        entry['note'] = note
    entry_id = raw.get('id')
    if not isinstance(entry_id, str) or not QUOTA_ID.fullmatch(entry_id) \
            or entry_id in used_ids:
        entry_id = 'q' + uuid.uuid4().hex[:10]
    used_ids.add(entry_id)
    return {'id': entry_id, **entry}


def _quota_list(value):
    """Validate a full quota-time list for a write; reject instead of trimming."""
    if not isinstance(value, list):
        raise RuntimeError('额度时间格式不正确。')
    if len(value) > MAX_QUOTA_TIMES:
        raise RuntimeError(f'额度时间最多 {MAX_QUOTA_TIMES} 条。')
    used_ids = set()
    return [_quota_entry(raw, used_ids) for raw in value]


def _saved_quota_list(value):
    """Tolerant read: keep valid entries, drop bad ones, cap the list."""
    if not isinstance(value, list):
        return []
    used_ids = set()
    entries = []
    for raw in value[:MAX_QUOTA_TIMES]:
        try:
            entries.append(_quota_entry(raw, used_ids))
        except RuntimeError:
            continue
    return entries


def _normalize_rows(raw):
    """Tolerant canonical form: drop bad rows, keep at most one test item."""
    rows = []
    seen_test = False
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, dict):
            continue
        code, title = row.get('code'), row.get('title')
        if not (isinstance(code, str) and CODE.fullmatch(code)
                and isinstance(title, str) and 1 <= len(title) <= TITLE_MAX):
            continue
        item = {'code': code, 'title': title}
        amount = row.get('test_amount')
        if not seen_test and isinstance(amount, (str, int, float)) \
                and not isinstance(amount, bool):
            try:
                item['test_amount'] = amount_text(amount)
                seen_test = True
            except RuntimeError:
                pass
        quota = _saved_quota_list(row.get('quota_times'))
        if quota:
            item['quota_times'] = quota
        rows.append(item)
    return rows


def load():
    try:
        raw = json.loads(PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    return _normalize_rows(raw)


def save(rows):
    normalized = _normalize_rows(rows)
    PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = PATH.with_suffix('.tmp')
    temp.write_text(json.dumps(normalized, ensure_ascii=False) + '\n', encoding='utf-8')
    temp.chmod(0o600)
    temp.replace(PATH)
    return normalized


def add(code, title):
    code = (code or '').strip()
    title = _title_text(title)
    if not CODE.fullmatch(code):
        raise RuntimeError('产品代码须为 4–20 位字母或数字。')
    rows = load()
    for row in rows:
        if row['code'].lower() == code.lower():
            # Keep test_amount and quota_times: renaming must not clear settings.
            row['code'], row['title'] = code, title
            return save(rows)
    if len(rows) >= MAX_ITEMS:
        raise RuntimeError('收藏数量已达上限。')
    rows.append({'code': code, 'title': title})
    return save(rows)


def remove(code):
    code = (code or '').strip()
    return save([row for row in load() if row['code'].lower() != code.lower()])


def set_test(code, amount):
    """Mark one favourite as the test item; the amount is required."""
    code = (code or '').strip()
    value = amount_text(amount)
    rows = load()
    match = next((row for row in rows if row['code'].lower() == code.lower()), None)
    if match is None:
        raise RuntimeError('先收藏这个产品，再设为测试项。')
    for row in rows:
        row.pop('test_amount', None)
    match['test_amount'] = value
    return save(rows)


def clear_test():
    rows = load()
    for row in rows:
        row.pop('test_amount', None)
    return save(rows)


def test_item():
    """The test item, if any: {'code', 'amount', 'title'}."""
    for row in load():
        amount = row.get('test_amount')
        if amount:
            return {'code': row['code'], 'amount': amount, 'title': row.get('title', '')}
    return None


def save_item(payload):
    """Upsert one favourite from an Agent/App settings payload.

    Keys are applied only when present, so a partial update keeps the rest:
    `title` (new items require it), `test_amount` (null/'' clears this item
    only), and `quota_times` (a full replacement list, `[]` clears it).
    """
    if not isinstance(payload, dict):
        raise RuntimeError('收藏设置格式无效。')
    code = payload.get('code')
    if not isinstance(code, str) or not CODE.fullmatch(code.strip()):
        raise RuntimeError('产品代码须为 4–20 位字母或数字。')
    code = code.strip()
    rows = load()
    match = next((row for row in rows if row['code'].lower() == code.lower()), None)
    if match is not None:
        if 'title' in payload:
            match['title'] = _title_text(payload.get('title'))
    else:
        if 'title' not in payload:
            raise RuntimeError('新增收藏需要同时提供标题。')
        title = _title_text(payload.get('title'))
        if len(rows) >= MAX_ITEMS:
            raise RuntimeError('收藏数量已达上限。')
        match = {'code': code, 'title': title}
        rows.append(match)
    if 'quota_times' in payload:
        entries = _quota_list(payload.get('quota_times'))
        if entries:
            match['quota_times'] = entries
        else:
            match.pop('quota_times', None)
    if 'test_amount' in payload:
        amount = payload.get('test_amount')
        if amount is None or amount == '':
            match.pop('test_amount', None)
        else:
            value = amount_text(amount)
            for row in rows:
                row.pop('test_amount', None)
            match['test_amount'] = value
    return save(rows)
