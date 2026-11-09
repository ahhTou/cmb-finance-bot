---
name: paged-scroll
description: 两屏页面（如历史页）滚动必须累计约 100px 才整屏切换，页面不能跟手滚动
type: feedback
updated: 2026-11-09
---

用户 2026-11-09 两次纠正历史页的滚动方式：只加 CSS `scroll-snap` 不够——手势过程中页面仍会跟手滚动。要求是**虚拟滚动**：滚轮/触控板累计约 **100px** 才整屏切到上一/下一屏，不足阈值时页面完全不动；到第一/第二屏边界后同方向继续滚不再移动。

实现方式（见 `desktop/src/pages/History.tsx`）：在滚动容器上监听 `wheel`（`passive: false`）并 `preventDefault`，累计 `deltaY`（`deltaMode` 为行/页时先换算成像素），达到 `WHEEL_TRIGGER_PX = 100` 才 `scrollTo` 到 `clientHeight` 的整数倍；方向变化重置累计；嵌套可滚动区域（如第二屏的记录列表）保留原生滚动，滚到边界后再继续才切屏。

**原因：** 账户持有人把两屏页面当虚拟屏使用，不接受手势中间的跟随滚动。
**怎么用：** 以后再做两屏/分屏式页面时直接复用这套 wheel 分页处理，不要只靠 `snap-y`。
