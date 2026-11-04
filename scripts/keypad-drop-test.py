#!/usr/bin/env python3
"""Manual diagnostic: measure dropped taps on the CMB payment keypad.

背景
  支付密码键盘会把同一坐标上的快速重复点击合并。如果密码相邻两位
  相同（11、22 之类），连点就会少输入一位，只剩 5 位，「确定」也
  不会变为可用。

做法
  只打开一次购买页（dry run，不输入真实密码、不提交），然后循环：
  用 30 次「删除」清空，输入一组固定测试数字，读取「确定」是否可用。
  「确定」只在 6 位时可用，所以输入 6 次后仍不可用，就说明至少有
  一次点击被合并。

安全边界
  - 只使用固定测试数字，不读取、不输入、不记录账户密码；
  - 从不点击「确定」「完成」，从不提交，不产生交易；
  - 全程只打开一次购买页，避免反复唤起。

2026-11-04 实测（320x640 模拟器，每项 20 轮）
  同一数字、无间隔        11 轮少一位
  同一数字、50ms 间隔      0 轮
  不同数字、无间隔         0 轮
  不同数字、10ms 间隔      0 轮

用法
  python3 scripts/keypad-drop-test.py --rounds 20
  python3 scripts/keypad-drop-test.py --rounds 20 --digits 135790 --gap 0.01
  python3 scripts/keypad-drop-test.py --rounds 20 --digits 111111 --gap 0

退出码：任一轮掉键返回 1，全部完整返回 0，便于人工验收时作为门槛。
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import fast_buy_uia2 as fu  # noqa: E402

CODE, AMOUNT = "133045A", "0.01"
CLEAR_TAPS = 30
CONFIRM_WAIT = 0.15


def tap_commands(digits, keys, gap):
    """`gap=None` uses the production policy; `gap=0` means back-to-back."""
    if gap is None:
        return fu.password_taps(digits, keys, CONFIRM_WAIT)
    commands = []
    for index, digit in enumerate(digits):
        commands.append(f"input tap {keys[digit][0]} {keys[digit][1]}")
        if index < len(digits) - 1 and gap > 0:
            commands.append(f"sleep {gap}")
    commands.append(f"sleep {CONFIRM_WAIT}")
    return commands


def main():
    parser = argparse.ArgumentParser(description="测量支付密码键盘的掉键率")
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--digits", default="111111",
                        help="固定测试数字，六位；不要使用真实密码")
    parser.add_argument("--gap", type=float, default=None,
                        help="每两位之间的固定间隔；0 表示背靠背；省略表示生产策略")
    args = parser.parse_args()
    if not args.digits.isdigit() or len(args.digits) != 6:
        parser.error("--digits 必须是六位数字")

    fu.run(CODE, AMOUNT, dry_run=True, form_deadline=10)
    root, keys = fu.wait_keypad_stable()
    clear = fu.center_of(fu.find_node(root, "删除"))
    failed = 0
    try:
        for index in range(args.rounds):
            fu.send_commands([f"input tap {clear[0]} {clear[1]}"] * CLEAR_TAPS)
            time.sleep(0.45)
            fu.send_commands(tap_commands(args.digits, keys, args.gap))
            time.sleep(0.30)
            usable = fu.confirm_enabled(fu.dump())
            failed += 0 if usable else 1
            print(f"{index + 1:2d}/{args.rounds} 确定={'可用' if usable else '不可用'}",
                  flush=True)
    finally:
        try:
            fu.close_password_panel()
        except Exception:
            pass
    print(f"== {args.rounds} 轮，掉键 {failed} 轮（{failed / args.rounds:.0%}）")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
