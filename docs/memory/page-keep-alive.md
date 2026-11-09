---
name: page-keep-alive
description: 侧边栏切菜单后页面状态要保留：按页面配置 keepAlive，目前只开计划页
type: feedback
updated: 2026-11-09
---

用户 2026-11-09 要求：从「计划」菜单切走再回来，计划页里正在填写/保存的内容不能丢。做法是给侧边栏页面加可选保活：`desktop/src/router.tsx` 的 `PAGES` 里标了 `keepAlive: true` 的页面第一次打开后保持挂载，切别的菜单时只加 `hidden`（`display: none`）隐藏，回来时组件状态、时间线/周视图选择和滚动位置都还在；没标的页面仍按原行为卸载重挂。目前只开「计划」页；值守中的任务专注视图（`LivePage`）打开时，整块页面栈也保持挂载只隐藏，从专注视图切回计划同样不丢草稿。

**原因：** 页面状态（计划草稿、视图模式、滚动位置）只存在组件里，组件卸载就没了；账户持有人切菜单看别的页面是常态，不接受回来重新填。

**怎么用：** 以后新页面需要跨菜单保留状态时，把状态放组件内并在 `PAGES` 里开 `keepAlive`，不要为此引入全局 store 或把草稿搬进 TanStack Query。手动验收项见 `docs/app-ui-test-plan.md` §P。
