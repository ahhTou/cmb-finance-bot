"""Non-secret purchase preferences; watch tasks snapshot these at arming."""
import json
from pathlib import Path

SETTINGS = Path(__file__).resolve().parents[1] / 'var/night/purchase-settings.json'
DEFAULTS = {
    'reopen_deadline': 60, 'drill_form_deadline': 10,
    'cold_start_minutes': 7,
    'first_offset_ms': 200, 'first_max_retries': 5,
    'irregular_advance_ms': 200, 'irregular_window_minutes': 5,
    'irregular_retry_min_ms': 50, 'irregular_retry_max_ms': 250,
}
LIMITS = {
    'reopen_deadline': (1, 300), 'drill_form_deadline': (1, 300),
    'cold_start_minutes': (2, 60),
    'first_offset_ms': (0, 10000), 'first_max_retries': (0, 100),
    'irregular_advance_ms': (0, 10000), 'irregular_window_minutes': (1, 60),
    'irregular_retry_min_ms': (1, 60000), 'irregular_retry_max_ms': (1, 60000),
}


def validate(values):
    if not isinstance(values, dict) or set(values) - DEFAULTS.keys():
        raise RuntimeError('购买设置格式无效。')
    result = dict(DEFAULTS, **values)
    for key, value in result.items():
        lower, upper = LIMITS[key]
        if type(value) is not int or not lower <= value <= upper:
            raise RuntimeError(f'{key} 必须为 {lower}–{upper} 的整数。')
    if result['irregular_retry_min_ms'] > result['irregular_retry_max_ms']:
        raise RuntimeError('随机重试间隔下限不得大于上限。')
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


def revision(values):
    import hashlib
    canonical = json.dumps(validate(values), sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode()).hexdigest()
