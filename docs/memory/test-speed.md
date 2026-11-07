---
name: test-speed
description: 单元测试可以写细，但不许耗时——测试必须隔离模拟器、网络和 adb
type: feedback
updated: 2026-11-05
---

测试要写好，但**不能耗时**。一次测试跑几分钟，用户会直接打断。

用户原话（2026-11-05）："测试可以写好，不要写耗时的测试"。

**原因：** 给布防加网络前置检查后，`ensure_network()` 在单元测试里真的跑了：轮询 15 次 × 2 秒 = 30 秒，失败还会调 `restart_emulator()` 去重启模拟器。`tests/test_night_watch.py` 单次跑 181 秒，`test_redemption` 卡到超时，`test_watch_recovery` 的并发用例 10 秒超时。用户连续两次打断。

**怎么用：**

- 单元测试**绝不**碰真实外部世界：`adb`、模拟器、网络、`ps`、钥匙串都必须 patch。
- 新增外部依赖时要同步给测试加默认 mock，默认值取"正常可用"，需要失败路径的用例单独 override。给 `arm` 加网络检查后，`test_redemption` / `test_watch_recovery` 都应默认 `network_state` 返回 `up`。
- "诊断信息"类函数（如 `wifi_never_validated`）要吞掉全部异常：它不该因为 MagicMock 或环境异常而让主流程崩掉，更不该在正常路径多查一次。
- 改完必须跑 `time python3 -B -m unittest discover -s tests -p "test_*.py"` 确认总时长。当前基线约 **2 秒**；超过 10 秒说明有测试在等真实环境。
- 测试必须全过；`tests/test_timed_buy.py` 的旧报错已在 2026-11-07 修掉（数字键 fixture 的控件类名不对），不要再把它当已知失败。
