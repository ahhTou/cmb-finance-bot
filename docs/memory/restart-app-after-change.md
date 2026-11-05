---
name: restart-app-after-change
description: 改完代码后，若当前没有值守，默认重新构建并重启管理 App，让用户立即看到效果
type: feedback
updated: 2026-11-05
---

改完需要重建或重启 App 才能生效的代码（见 `AGENT_WORKFLOW.md` §2A.4 的表）后，先查 `night_watch.py status`：没有正在进行的值守（阶段不是 `armed` / `preparing` / `waiting` / `firing`，或进程未运行），就直接按 §2A.2、§2A.3 构建并重启 App，不用先问。

**原因：** 用户 2026-11-05 明确要求“改完如果当前没有值守默认重启 App 立即看到效果”。

**怎么用：** 有值守在跑时不重启（重启本身不影响值守进程，但仍以用户确认为准），在回复里说明还没重启。只改了不需要重启的文件（如 `night_watch.py`、`query_gate.py`）时不必重启。构建参考：2026-11-05 一次 `pnpm tauri build` 的 Rust 增量编译 11 秒，整条命令一分钟以内。
