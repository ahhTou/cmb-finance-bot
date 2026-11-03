# 管理 App「招行理财值守」实现进度

更新：2026-11-03。状态：**第一版已实现，构建与界面检查通过，设备和凭据端到端验收待账户持有人执行。**

当前开发分支：`codex/macos-admin-app`，尚未合并到 `main`，未推送。本文件记录当前实现和剩余验收，不再保留已经被替换的菜单栏、自绘红绿灯及顶部导航方案。

接手先读 `README.md`、`AGENT_WORKFLOW.md` §0、§1、§7、§9。真实提交、布防、撤单与凭据写入由账户持有人操作；Agent 不执行这些验收动作。

## 已完成

| 部分 | 当前实现 |
|---|---|
| 前台 App | AppKit 原生窗口承载 SwiftUI，最低 macOS 13，自用本机签名，无第三方 Swift 依赖 |
| 导航 | 左侧栏：状态、系统、布防、设置；项目目录、Python 路径与凭据统一在设置中 |
| 样式 | 纯深灰背景 `#1E1E1E`，无描边卡片 `#292929`；保留系统原生圆角、阴影和红绿灯 |
| 窗口行为 | 无菜单栏或 Dock 图标；双击打开/唤起；关闭与 Cmd-W/Cmd-Q 二次确认，退出不主动取消独立值守 |
| 布局 | 主滚动条贴窗口最右侧；九宫格与交易密码卡片按内容自动等高；切换页面保留布防输入，离开设置清空敏感输入 |
| 图标 | 红色圆徽、白色八爪鱼、镂空红眼和连接身体的横线；分层矢量源随工程构建 |
| Python 接口 | 单行 JSON，统一成功/错误输出、设备检查、系统检查、历史、布防、取消、恢复、凭据同步与 Agent 心跳 |
| 值守保护 | 版本 2 任务、文件锁、原子写、心跳、提交标记、任务和运行代次、恢复预算及终态历史 |
| 项目 Skill | 仅在项目 `skills/cmb-watch/SKILL.md`；复制指令生成当前项目的绝对路径，不使用 Claude 目录或全局安装 |
| 文档与测试 | README、执行手册及隔离测试已同步；验证详情见下文 |

## 架构与构建

```text
CMBFinanceBot.app
 ├─ AppKit：原生窗口、菜单快捷键、关闭确认
 ├─ SwiftUI：状态 / 系统 / 布防 / 设置
 └─ Backend.run：Process + stdin / stdout / stderr
      └─ python3 -B src/admin_cli.py
           ├─ night_watch：任务、后台值守、恢复与历史
           ├─ manage：项目专用模拟器和 ADB
           ├─ keychain_store：唯一凭据读写方
           └─ notify：邮件配置状态
```

```sh
./scripts/build-app
open app/CMBFinanceBot/build/Build/Products/Release/CMBFinanceBot.app
```

也可打开 `app/CMBFinanceBot/CMBFinanceBot.xcodeproj`，运行 `CMBFinanceBot` scheme。构建产物和 Xcode 用户状态不进 Git。

- 工程名 `CMBFinanceBot`，bundle id `local.cmb-finance-bot.app`，显示名「招行理财值守」。仓库与钥匙串条目不改名。
- 首次运行自动进入设置，选择项目目录和 Python 绝对路径，保存到 `UserDefaults`。App Sandbox 关闭，默认 Python 为 `/usr/bin/python3`。
- `Backend.run` 在选定项目目录下运行 CLI。敏感值只用 stdin JSON，stdout/stderr 并行排空，错误只展示后端文案；一般超时 30 秒，启动模拟器 60 秒。
- App 不直接访问 ADB 或钥匙串。凭据仍由 Python 写到现有条目，回读验证；App 只展示配置状态。

## 四个页面

### 状态

展示当前任务的产品、金额、时间、阶段、演练标记、进程、图案次数、心跳、Agent 状态和最近 30 行日志。心跳超过五分钟提示异常；旧任务显示不可恢复。

支持刷新设备、启停模拟器、截图、复制监听指令。活动任务 `armed / preparing / firing` 期间禁止关闭模拟器。进入提交后进程退出时，提示先查交易记录，不补单、不重试。

### 系统

只读检查 Mac 电源、合盖、休眠设置、值守 caffeinate、网络，以及模拟器屏幕、常亮、模拟 AC、熄屏与锁屏状态。网络通过银行域名的 TLS 握手测量，超过一秒或失败显示异常。

电源和合盖展示可读摘要，连接耗时保留三位小数；原始休眠设置折叠显示。锁屏状态目前返回“无法读取”，不推断真实锁定状态。只提供恢复模拟器常亮，不修改 Mac 设置。

### 布防

仅实现首发模式，捡漏和赎回抢购仍规划中。产品、金额、开售时间、准备分钟数由 Python 最终校验；演练默认开启，立即排练只能在演练状态使用。真实布防必须再次输入相同金额。

取消布防在 `firing` 时禁用；历史显示最近 20 条终态事件。同一次任务恢复后可能留下多条事件，不代表新增购买。结果以银行交易记录为准。

### 设置

项目目录、Python 路径、凭据配置状态和邮件是否配置集中显示。

九宫格选择 4–9 个不重复点，画两次一致后保存。交易密码使用当前、新值和确认三个安全输入框，由 Python 核对当前值并校验新值。设置仅同步脚本保存的凭据，不修改银行 App 的设置。准备/提交阶段和操作忙碌时禁用修改，离开设置清空输入。

窗口每五秒刷新 `status`，模型另有每分钟兜底刷新；`device`、`system` 在进入对应页面或手动刷新时读取。阶段变化尝试发送系统通知，仍需验收系统授权与实际送达。

## Python CLI

每个业务命令向 stdout 输出一行 JSON。成功 `ok: true`、退出码 0；失败 `ok: false`、中文 `error`、退出码 1。无需 `--json`。

| 命令 | 行为 |
|---|---|
| `status` | 任务、日志、进程与双心跳；不调 ADB。配置状态会检查钥匙串，但不返回凭据值，可能触发系统授权 |
| `device` | 设备/模拟器状态，ADB 单次超时五秒，并行读取 |
| `system` | 电源、合盖、防休眠、网络等只读检查 |
| `history` | 最近 20 条终态记录，忽略不完整 JSON 行 |
| `emulator start / stop` | 项目模拟器启停；启动后等待开机并恢复常亮；活动任务禁止 stop |
| `keep-awake` | 恢复项目模拟器常亮 |
| `screenshot` | 返回项目截图路径，不向外发送 |
| `arm --code --amount (--at / --now) --prep-minutes [--dry-run]` | 经原逻辑布防，后台进程独立运行；admin CLI 的 `--now` 必须同时演练 |
| `disarm` | 提交阶段拒绝，准备阶段仍可取消 |
| `resume --reason [--session] [--kill-stale] [--after-manual-login]` | 按原任务恢复，不修改产品、金额、时间或图案预算 |
| `set-login-pattern` | stdin `{"new": "..."}`；拒绝在 argv 携带值 |
| `set-payment-password` | stdin `{"current": "...", "new": "..."}`；拒绝在 argv 携带值 |
| `agent-heartbeat --session --interval` | 写当前布防的监听心跳，间隔 30–3600 秒 |
| `agent-release` | 删除监听心跳 |

现有 `night_watch.py arm / status / disarm`、购买、撤单和 `keychain_store.py update-login` 入口保留。新增 `night_watch.py resume`；版本 2 的内部 `run` 必须由布防或恢复传入运行代次，不应手工调用。

## 恢复与并发边界

- 任务新建时写 `version: 2`、`task_id`、`generation`、`last_tick` 和 `resumes`；进入购买流程前同次写入 `phase=firing` 与 `fired_at`，之后不能删除或更改提交标记。
- `arm / resume / disarm` 全流程持有非阻塞 `task.lock`；拿不到就拒绝，不排队。后台更新持有阻塞锁并检查任务、运行代次和取消状态，旧进程不能覆盖新任务。写 JSON 使用临时文件再改名。
- `resume` 只接受版本 2、无 `fired_at`、阶段 `armed / preparing / aborted` 的任务。旧任务可查看和取消，不能恢复。
- 离 `fire_at` 必须超过三分钟，模拟器已开机，每次布防最多恢复两次；沿用原参数和累计图案次数。
- 进程存活时须心跳超五分钟且显式 `--kill-stale`。终止前核对项目命令与进程组，无法确认身份就拒绝。先 SIGTERM，超时才 SIGKILL。
- 图案达三次时，须持有人明确表示已手动登录并使用 `--after-manual-login`；准备阶段不冷启动、不画图案，确认不了登录即停止。
- `done / aborted / disarmed` 追加 `var/night/history.jsonl`。其他运行数据也只在忽略的 `var/night/` 下，不进仓库。

## Agent 监听

规则唯一实现为 `skills/cmb-watch/SKILL.md`。App 复制的指令类似：

```text
读取项目 Skill「/绝对项目路径/skills/cmb-watch/SKILL.md」，用 cmb-watch 监听当前布防。
```

开始监听需用户要求。Skill 约定故障检测、双心跳、提交前恢复、取消/手动登录的逐次授权以及结束清理。相同状态保持安静；只有故障、恢复、结果或需要用户操作时通知。

App 不托管 Agent，也不保证某个环境具有 Monitor、手机通知或持续运行能力。缺少这些工具时必须说明限制，不能声称已经整夜监听。通知渠道依用户授权，不自动向其他人发消息。

## 验证结果

### 已通过

- 相关 Python 测试 55 项：

  ```sh
  python3 -B -m unittest tests.test_night_watch tests.test_watch_recovery tests.test_admin_cli tests.test_amount tests.test_open_form
  ```

  覆盖旧流程、恢复拒绝条件、文件锁、两进程竞争、旧代次写回、提交标记、图案预算、手动登录路径、心跳、凭据 argv/stdin 边界和系统输出解析。使用临时目录与 mock，不操作真实银行或凭据。

- Swift 桥接隔离测试：

  ```sh
  swiftc -parse-as-library -module-cache-path /tmp/cmb-swift-module-cache app/CMBFinanceBot/Backend.swift tests/BackendSmoke.swift -o /tmp/cmb-backend-smoke
  /tmp/cmb-backend-smoke
  ```

  验证 JSON、stdin、较大 stderr 不阻塞、非零退出错误。

- Release 构建、`codesign --verify --deep --strict`、Skill 格式校验和 `git diff --check`。
- 实际 UI 检查：启动、重复打开、页面导航、设置归类、复制指令绝对路径、未提交布防输入在页面切换后保留、关闭确认及取消关闭。已查看原生红绿灯无遮挡、系统圆角、滚动条最右侧和密码卡片等高布局；阴影由系统启用。
- 用独立的一秒测试进程确认 caffeinate 独立进程组；这不是完整设备值守验收。

### 已知限制

- 全量 `unittest discover` 有既有错误：废弃 `test_timed_buy.test_single_submit_success` 的数字键测试失败（执行手册 §8 已记录），本次不修改该路径。
- 当前系统 Python 的 urllib3/LibreSSL 警告仍存在，不影响上述隔离测试通过。
- 未实现捡漏、赎回抢购、登录启动开关、远程 UI、签名公证；锁屏检测暂无可靠实现。
- 监听 Skill 已落地，但没有运行真实整夜监听、手机通知或恢复故障注入验收。

## 下一步验收（账户持有人执行）

1. App 设置项目路径后确认四页与真实设备一致；模拟器未运行时界面仍可操作。确认系统通知授权、阶段变化通知和真实网络检查。
2. 首先用 App 做演练，检查启动准备、到密码页停止、历史记录。中途退出 App 再重开，确认值守仍独立运行；不能只以一秒 caffeinate 测试替代。
3. 持有人亲自同步图案和交易密码，再在自己的终端演练验证回读；检查日志、进程参数和通知不含凭据。Agent 不输入或读取真实值。
4. 恢复故障演练使用至少十五分钟后的开售时间、`--prep-minutes 5 --dry-run`。不要用只剩三分钟的 `--now` 验证五分钟心跳超时。验证进程退出、卡住、模拟器退出、最多两次恢复、手动登录，以及 `fired_at` 后一律拒绝恢复。
5. 新 Agent 会话读取项目 Skill 后监听演练，检查心跳、失联提示、可用通知渠道和结束释放。工具能力不足时记录具体限制。
6. 做完以上检查后再考虑真实布防；保留最终以银行交易记录为准的核对流程。
