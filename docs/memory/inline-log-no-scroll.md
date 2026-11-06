---
name: inline-log-no-scroll
description: 内嵌日志预览（最近日志、值守日志）不要滚动条，完整日志只在弹窗里看
type: feedback
updated: 2026-11-06
---

用户 2026-11-06 原话：“图1、图2 区域不要有滚动条，日志区域也不要有滚动条，想看日志就看点开日志弹窗看。”

**原因：** 状态页「最近日志」卡片和历史页「值守日志」当时用 `overflow-auto`，日志行很长时出现横/纵向滚动条，挤占卡片、破坏页面整洁；用户希望页面不出现日志滚动条，完整日志通过「查看日志 / 查看全部」弹窗查看。

**怎么用：** 新增内嵌日志区时用 `desktop/src/components/shared.tsx` 的 `LogPreview`（只显示最新的整行、长行截断、不滚动；`fitLines` 用于高度由 flex 固定出来的预览），不要再用 `LogText` 或给内嵌日志加 `overflow-auto`；完整日志放 `LogDialog` 或对应弹窗。状态页卡片可用 `DashboardCard scrollBody={false}` 关掉卡片自身的滚动。
