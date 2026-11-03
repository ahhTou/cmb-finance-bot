---
name: project-location
description: 项目在 2026-11-03 从 ~/Dev/Playground/cmb-finance-bot 迁到 ~/Dev/cmb-finance-bot；旧路径会出现在日志、旧会话和虚拟设备配置里
type: project
updated: 2026-11-03
---

项目根目录是 `/Users/ahhtou/Dev/cmb-finance-bot`，和 `~/Dev/Playground` 同级。2026-11-03 之前它在 `~/Dev/Playground/cmb-finance-bot`。

迁移时已改过的地方：
- `AGENT_WORKFLOW.md` 里的 `cd` 路径；
- 虚拟设备配置 `var/avd/cmb_finance.ini`、`var/avd/cmb_finance.avd/hardware-qemu.ini`、`emu-launch-params.txt`。

仍会看到旧路径的地方（不用改）：
- `var/night/watch.log` 等历史日志；
- 迁移前的 Claude Code 会话（如 11-03 的首发布防会话），它们的工作目录还是旧路径，不能在里面继续操作本项目。

代码里没有写死路径，都用 `Path(__file__)` 推算项目根目录。

**原因：** 用户希望项目作为独立 Git 仓库，不放在闲聊用的 Playground 里。
**怎么用：** 看到旧路径不要照着 `cd`；如果模拟器启动报找不到镜像或磁盘，先查 `var/avd/` 里的配置是否还有旧路径。
