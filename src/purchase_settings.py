"""Non-secret purchase preferences; watch tasks snapshot these at arming."""
import json
from pathlib import Path

SETTINGS = Path(__file__).resolve().parents[1] / 'var/night/purchase-settings.json'
DEFAULTS = {
    'reopen_deadline': 60, 'drill_form_deadline': 10,
    'cold_start_minutes': 7,
    'first_offset_ms': 200, 'first_max_retries': 5,
    'irregular_advance_ms': 200, 'irregular_window_minutes': 2,
    # Redemption backoff, measured from the planned first query: a burst tier,
    # a linear ramp, a slow tier, then an idle tier until the window ends.
    # 11-05: quota reappeared ~18 s after 09:00, just past the old 15 s burst.
    'irregular_retry_min_ms': 300, 'irregular_retry_max_ms': 500,
    'irregular_burst_seconds': 60, 'irregular_ramp_seconds': 65,
    'irregular_slow_min_ms': 1000, 'irregular_slow_max_ms': 2000,
    'irregular_idle_after_seconds': 90,
    'irregular_idle_min_ms': 2500, 'irregular_idle_max_ms': 4000,
}
LIMITS = {
    'reopen_deadline': (1, 300), 'drill_form_deadline': (1, 300),
    'cold_start_minutes': (0, 60),
    'first_offset_ms': (0, 10000), 'first_max_retries': (0, 100),
    'irregular_advance_ms': (0, 10000), 'irregular_window_minutes': (1, 60),
    'irregular_retry_min_ms': (1, 60000), 'irregular_retry_max_ms': (1, 60000),
    'irregular_burst_seconds': (0, 3600), 'irregular_ramp_seconds': (0, 3600),
    'irregular_slow_min_ms': (1, 60000), 'irregular_slow_max_ms': (1, 60000),
    'irregular_idle_after_seconds': (0, 3600),
    'irregular_idle_min_ms': (1, 60000), 'irregular_idle_max_ms': (1, 60000),
}
PAIRS = (('irregular_retry_min_ms', 'irregular_retry_max_ms', '高频'),
         ('irregular_slow_min_ms', 'irregular_slow_max_ms', '降频'),
         ('irregular_idle_min_ms', 'irregular_idle_max_ms', '低频'))


def validate(values):
    if not isinstance(values, dict) or set(values) - DEFAULTS.keys():
        raise RuntimeError('购买设置格式无效。')
    result = dict(DEFAULTS, **values)
    for key, value in result.items():
        lower, upper = LIMITS[key]
        if type(value) is not int or not lower <= value <= upper:
            raise RuntimeError(f'{key} 必须为 {lower}–{upper} 的整数。')
    for lower, upper, name in PAIRS:
        if result[lower] > result[upper]:
            raise RuntimeError(f'{name}阶段随机间隔下限不得大于上限。')
    if not (result['irregular_burst_seconds'] <= result['irregular_ramp_seconds']
            <= result['irregular_idle_after_seconds']):
        raise RuntimeError('分段时间须满足：高频结束 ≤ 过渡结束 ≤ 进入低频。')
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
