---
name: app-ui-screenshots
description: 管理 App 界面截图放在 docs/images/，用 pnpm screenshots 在假后端上重拍，不碰真实值守
type: project
updated: 2026-11-07
---

README「管理 App → 界面」一节的截图在 `docs/images/app-*.png`（任务 / 布防中 / 状态 / 演练 / 设置 / 推送通知）。在 `desktop/` 下运行 `pnpm screenshots` 重拍：脚本起一个假后端（MSW）的 Vite 服务，用 WebKit 按 1093×763、2 倍像素截图，数据全是演示数据。推送通知那张会打开「凭据」页签并滚动到卡片。

**不要用真实环境拍「布防中」**：`arm` 会启动真实盯盘进程、到点会提交交易。假后端的 `armed` 场景就是布防中的演示态，不需要再改 `var/night/` 下的文件。

**原因：** 仓库要公开，截图里不能出现真实产品代码、金额和历史交易日志。

**怎么用：** 界面改动后重拍截图就跑 `pnpm screenshots`；新增场景改 `desktop/src/mocks/fixtures.ts`。
