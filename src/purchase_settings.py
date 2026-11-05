"""Non-secret purchase preferences; watch tasks snapshot these at arming."""
import json
from pathlib import Path

SETTINGS = Path(__file__).resolve().parents[1] / 'var/night/purchase-settings.json'
# The experimental native-password path was removed after the 2026-11-05
# crash. Old settings/task snapshots may still carry this retired key; drop
# it on load instead of rejecting the whole file.
RETIRED = {'simulate_password_input'}
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
    # 密码流程的等待时间：前（等密码页、等键盘就绪）、中（相邻两位之间的
    # 间隔）、后（点确定到读结果）。安全键盘是同一个 adb shell 里的一串
    # `input tap` + `sleep`，所以每段停顿都能单独调；同一位数字连按会被 App
    # 合并成一位（11-20 次里 5 次只进 5 位），所以相同数字的间隔更长。
    # 单位：*_ms 毫秒，*_s 秒。
    'password_page_timeout_s': 10,        # 风险确认 → 密码面板出现
    'keypad_timeout_ms': 1200,            # 等焦点 + 10 键可用 + 位置稳定
    # 11-05 晚 18 次演练：密码页识别出来时键盘已停稳，第 1 次采样起布局就
    # 不再变化；2 次 / 60ms 在 93–183ms 就绪，6 位全部第一轮输入成功。
    'keypad_stable_ms': 60,               # 连续不动多久才认为键盘就绪
    'keypad_stable_samples': 2,           # 至少连续几次采样不动
    # 两次采样之间额外 sleep。读一次控件树本身约 0.1 秒，已经是节拍；原来再
    # 加 40ms 时第 3 次采样要到约 280ms 才到，实测稳定 227–314ms（11-05）。
    'keypad_sample_gap_ms': 0,
    'password_same_digit_gap_ms': 50,     # 相邻两位相同，如 11、22
    'password_different_digit_gap_ms': 10,  # 相邻两位不同
    'password_confirm_gap_ms': 150,       # 最后一位输完 → 点确定
    'password_confirm_timeout_ms': 600,   # 点确定前等按钮变为可用
    'password_retry_gap_ms': 100,         # 清空重输前
    'password_done_gap_ms': 150,          # 点「完成」兜底后
    'password_close_wait_ms': 500,        # 关闭密码框后
    'result_first_wait_ms': 1000,         # 点确定 → 开始读结果
    'result_timeout_s': 20,               # 读结果最长等待
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
    'password_page_timeout_s': (1, 120),
    'keypad_timeout_ms': (100, 30000),
    'keypad_stable_ms': (0, 5000),
    'keypad_stable_samples': (2, 20),
    'keypad_sample_gap_ms': (0, 1000),
    'password_same_digit_gap_ms': (0, 3000),
    'password_different_digit_gap_ms': (0, 3000),
    'password_confirm_gap_ms': (0, 5000),
    'password_confirm_timeout_ms': (0, 30000),
    'password_retry_gap_ms': (0, 5000),
    'password_done_gap_ms': (0, 5000),
    'password_close_wait_ms': (0, 10000),
    'result_first_wait_ms': (0, 60000),
    'result_timeout_s': (1, 120),
}
PAIRS = (('irregular_retry_min_ms', 'irregular_retry_max_ms', '高频'),
         ('irregular_slow_min_ms', 'irregular_slow_max_ms', '降频'),
         ('irregular_idle_min_ms', 'irregular_idle_max_ms', '低频'))


def validate(values):
    if not isinstance(values, dict):
        raise RuntimeError('购买设置格式无效。')
    values = {key: value for key, value in values.items() if key not in RETIRED}
    if set(values) - DEFAULTS.keys():
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
    # wait_keypad_stable() only accepts a layout that has been still for
    # `keypad_stable_ms` and still has time left: an equal budget can never
    # succeed, so reject it here instead of aborting a real purchase.
    if result['keypad_stable_ms'] >= result['keypad_timeout_ms']:
        raise RuntimeError('键盘稳定时长必须小于等键盘上限，否则永远等不到就绪。')
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
