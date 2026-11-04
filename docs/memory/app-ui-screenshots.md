---
name: app-ui-screenshots
description: 管理 App 界面截图放在 docs/images/，README 怎么引用；拍"布防中"截图时怎样避免启动真实值守
type: project
updated: 2026-11-04
---

README「管理 App → 界面」一节的截图在 `docs/images/app-*.png`（任务 / 布防中 / 状态 / 演练 / 设置），窗口尺寸 1093×763、长边缩到 1366 后导出。

**拍布防中截图不要跑 `arm`**：`arm` 会启动真实的盯盘进程、到点会提交交易。做法是备份 `var/night/task.json` 和 `var/night/watch.log`，临时改写 task.json（`phase` 设为 `waiting`、`dry_run` 设为 `true`、产品代码用测试专用代码、`pid` 置空），清空日志后重启 App 截图，**截完立刻逐字节还原这两个文件**，并用 `admin_cli.py status` 核对 phase 与产品代码。

**原因：** 仓库要公开，截图里不能出现真实产品代码、金额和历史交易日志。

**怎么用：** 以后更新界面截图时照此办理；README 里已注明布防中那张是演练演示态。
