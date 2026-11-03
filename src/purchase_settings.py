"""Non-secret purchase-page retry preferences shared by CLI and App."""
import json
from pathlib import Path

SETTINGS = Path(__file__).resolve().parents[1] / 'var/night/purchase-settings.json'
DEFAULTS = {'reopen_deadline': 60, 'drill_form_deadline': 10}


def validate(values):
    if not isinstance(values, dict) or set(values) - DEFAULTS.keys():
        raise RuntimeError('购买页重试设置格式无效。')
    result = dict(DEFAULTS, **values)
    for value in result.values():
        if type(value) is not int or not 1 <= value <= 300:
            raise RuntimeError('购买页重试总时限必须为 1–300 秒的整数。')
    return result


def load():
    return validate(json.loads(SETTINGS.read_text())) if SETTINGS.exists() else dict(DEFAULTS)


def save(values):
    result = validate(values)
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    temp = SETTINGS.with_suffix('.tmp')
    temp.write_text(json.dumps(result) + '\n')
    temp.replace(SETTINGS)
    return result
