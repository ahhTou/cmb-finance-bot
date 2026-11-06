"""Saved product codes with a title, shared by the app and the terminal.

One row may be marked as the test item with an amount; drills use it as the
default product and amount instead of asking every time. At most one row is
the test item. Never stores times or credentials. The file is 0600 and
ignored by Git; entries are unique by case-insensitive code.
"""
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'var/favorites.json'
MAX_ITEMS = 100
CODE = re.compile(r'[A-Za-z0-9]{4,20}')
TITLE_MAX = 40


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


def load():
    try:
        raw = json.loads(PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    rows = []
    seen_test = False
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, dict):
            continue
        code, title = row.get('code'), row.get('title')
        if isinstance(code, str) and CODE.fullmatch(code) and isinstance(title, str) \
                and 1 <= len(title) <= TITLE_MAX:
            item = {'code': code, 'title': title}
            amount = row.get('test_amount')
            if not seen_test and isinstance(amount, (str, int, float)) \
                    and not isinstance(amount, bool):
                try:
                    item['test_amount'] = amount_text(amount)
                    seen_test = True
                except RuntimeError:
                    pass
            rows.append(item)
    return rows


def save(rows):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = PATH.with_suffix('.tmp')
    temp.write_text(json.dumps(rows, ensure_ascii=False) + '\n', encoding='utf-8')
    temp.chmod(0o600)
    temp.replace(PATH)
    return rows


def add(code, title):
    code = (code or '').strip()
    title = (title or '').strip()
    if not CODE.fullmatch(code):
        raise RuntimeError('产品代码须为 4–20 位字母或数字。')
    if not 1 <= len(title) <= TITLE_MAX:
        raise RuntimeError('标题须为 1–40 个字符。')
    rows = load()
    for row in rows:
        if row['code'].lower() == code.lower():
            # Keep test_amount: renaming a title must not clear the test item.
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
