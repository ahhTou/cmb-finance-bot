---
name: plan-page-layout
description: 计划页的固定版式：整页不滚动、状态条在底部、计划日志从刷新右侧手动打开
type: feedback
updated: 2026-11-10
---

用户 2026-11-10 对「计划」页提出：整个页面不要有滚动条；计划状态卡片放到计划视图下面并压薄，操作按钮改成大一点的圆形按钮；计划状态、计划视图都不要标题和描述；计划日志不要占页面，放到「刷新」的右侧，手动点开看。

**原因：** 计划页原来状态卡片在最上面、占掉半屏，日志卡片又在最下面，整页要滚动才能看到保存按钮和状态。账户持有人希望一屏内看全：上面编辑/看时间线，底部一条状态条加大按钮操作，日志按需弹窗查看。

**怎么用：** 改 `desktop/src/pages/Plan.tsx` 时保持这个版式：页面根节点 `flex min-h-0 flex-1 overflow-hidden`；计划视图 `flex-1 min-h-0`（只有时间线内部滚动，且用 `no-scrollbar` 隐藏滚动条）；状态条 `shrink-0` 放在最后、高度约 56px，操作按钮用 `RoundAction`（40px 圆形图标 + `title`/`aria-label`）；两张卡片不要再用 `Card` 的 title/subtitle。计划日志入口在 `desktop/src/router.tsx` 标题栏「刷新」按钮右侧，只在 `/plan` 显示，点开是 `Dialog` + `LogText`。e2e 有对应用例：`e2e/plan.spec.ts` 的无页面滚动条、状态条在下方 + 圆形按钮、计划日志入口三个用例。
