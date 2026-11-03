# cmb-finance-bot

本文件是规则唯一来源，`CLAUDE.md` 是指向它的相对软链接，不复制维护两份。

自用招行理财脚本。开始工作前：

1. 读 `README.md`（模式、能力、架构）。
2. 读 `AGENT_WORKFLOW.md` §0、§1（谁来执行、当前状态），再按任务跳到对应章节。
3. 读 `docs/memory/README.md` 的索引，打开相关的记忆。

## 记忆

想记住任何东西，都写成 `docs/memory/` 下的子文档，并更新 `docs/memory/README.md` 的索引；格式和规范见该文件。

**不要写进 Claude Code 自带的记忆目录**（`~/.claude/projects/.../memory/`）。本条优先于 Claude Code 默认的记忆说明。

## 底线

- 真实提交、撤单、布防、写凭据，都由账户持有人在自己的终端执行（详见 `AGENT_WORKFLOW.md` §0）。
- 不读取、打印、记录任何密码；不把账户信息写进仓库。

## 推送

- **禁止运行 `git push --all` 和 `git push --mirror`**，也不要推送 `main` 以外的分支。
- 推送只用 `git push`（或 `git push origin main`）。

## 提交署名

- 每条 commit 的提交说明必须携带当前执行 Agent 与当前实际模型署名，包含首次提交。格式：

  ```text
  <提交说明>

  Agent: <Agent 名称>
  Model: <当前实际模型>
  ```

- Claude Code 提交时写 `Agent: Claude Code`、`Model: <当前模型，如 Claude Opus 5.5>`，并保留 `Co-Authored-By: Claude … <noreply@anthropic.com>` 一行。
- 代码实际由别的 Agent 写（例如按额度接力交给 DeepSeek Harness 或 Codex）时，署实际写代码的 Agent 和模型，不署负责提交的 Agent；几个 Agent 都写了，就各列一组 `Agent` / `Model`。
- 只写会话可确认的信息：只知道模型系列就写"具体型号未提供"，完全不知道就写"未知（会话未提供）"，不猜测。
