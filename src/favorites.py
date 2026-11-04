"""Saved product codes with a title, shared by the app and the terminal.

Never stores amounts, times or credentials. The file is 0600 and ignored by
Git; entries are unique by case-insensitive code.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / 'var/favorites.json'
MAX_ITEMS = 100
CODE = re.compile(r'[A-Za-z0-9]{4,20}')


def load():
    try:
        raw = json.loads(PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    rows = []
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, dict):
            continue
        code, title = row.get('code'), row.get('title')
        if isinstance(code, str) and CODE.fullmatch(code) and isinstance(title, str) \
                and 1 <= len(title) <= 40:
            rows.append({'code': code, 'title': title})
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
    if not 1 <= len(title) <= 40:
        raise RuntimeError('标题须为 1–40 个字符。')
    rows = load()
    for row in rows:
        if row['code'].lower() == code.lower():
            row['code'], row['title'] = code, title
            return save(rows)
    if len(rows) >= MAX_ITEMS:
        raise RuntimeError('收藏数量已达上限。')
    rows.append({'code': code, 'title': title})
    return save(rows)


def remove(code):
    code = (code or '').strip()
    return save([row for row in load() if row['code'].lower() != code.lower()])
