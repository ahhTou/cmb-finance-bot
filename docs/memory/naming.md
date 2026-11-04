---
name: naming
description: 仓库、钥匙串条目、管理 App、Skill 的命名约定，以及为什么项目不改名
type: project
updated: 2026-11-04
---

| 用在哪 | 名字 |
|---|---|
| 仓库、目录 | `cmb-finance-bot` |
| 钥匙串条目 | `cmb-finance-bot.credentials.v1`、`cmb-finance-bot.smtp.v1` |
| README 标题 | 自用招行理财脚本 |
| 管理 App | `desktop/`，Tauri 标识 `local.cmb-finance-bot.desktop`，Rust 包 `cmb-desktop`，显示名"招行理财值守"（原生版的 `CMBFinanceBot` 已移除） |
| Agent 监听 Skill | `cmb-watch` |
| 购买模式 | 首发模式（已实现）、捡漏模式、不定时抢购模式（内部值 `redemption`，兼容历史任务） |

**原因：** 2026-11-03 用户问过要不要改项目名，决定不改：名字仍然准确；改名要迁移钥匙串凭据、重建虚拟设备，还会让旧记录里的路径对不上。
**怎么用：** 新增组件沿用上表的名字。不要改钥匙串条目名，改了现有凭据就读不到了。
