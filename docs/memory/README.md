# 项目记忆

这里存放 Agent 在工作中需要长期记住、但代码和其他文档里看不出来的信息。每条记忆是一个子文档，本文件是索引。

## 索引

- [项目位置](project-location.md)：2026-11-03 从 `~/Dev/Playground/` 迁到 `~/Dev/cmb-finance-bot`，旧路径会出现在哪里
- [命名约定](naming.md)：仓库、钥匙串、App、Skill 和模式的名称；不定时抢购保留内部值兼容
- [方案交接方式](plan-handoff.md)：用户把方案交给别的会话实现时，方案写在哪、怎么写
- [界面截图](app-ui-screenshots.md)：`docs/images/` 的截图用 `pnpm screenshots` 在假后端上重拍，不跑真实 `arm`

## 规范

**写在哪**

- 一条记忆一个文件：`docs/memory/<英文短横线命名>.md`。
- 写完在上面的"索引"里加一行：`- [标题](文件名.md)：一句话说明`。
- **不写进 Claude Code 自带的记忆目录**（`~/.claude/projects/.../memory/`）。那个目录不跟着仓库走，项目一迁移就对不上了。

**文件格式**

```markdown
---
name: <和文件名一致>
description: <一句话，用来判断以后是否相关>
type: user | feedback | project | reference
updated: YYYY-MM-DD
---

<内容。feedback 和 project 类型在后面加两行：>
**原因：** ...
**怎么用：** ...
```

- `user`：用户是谁、偏好什么。
- `feedback`：用户对工作方式的纠正或认可，要写原因。
- `project`：进行中的工作、决定和约束。相对日期一律换成绝对日期。
- `reference`：外部资源的位置（链接、看板等）。

**写什么、不写什么**

- 写之前先查索引。已有相关条目就更新它，不新建重复的；发现内容已过时或错误，就改掉或删除，并同步索引。
- 不写已经记录在别处的内容：
  - 操作步骤、当前状态、技术结论 → `AGENT_WORKFLOW.md`；
  - 架构和能力 → `README.md`；
  - 待实现的方案 → `docs/*-plan.md`；
  - 改了什么 → Git 历史。
- **绝不写**密码、九宫格图案、交易密码、SMTP 授权码、余额、账户信息。本目录会进 Git。
- 只对当前会话有用的东西不写。

**怎么用**

- 开始工作时读一遍索引，按 `description` 判断需要打开哪几条。
- 记忆反映的是写下时的情况。引用其中的文件、函数、命令前，先确认它们还在。
