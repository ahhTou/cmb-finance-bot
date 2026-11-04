# 管理 App「招行理财值守」实现进度

> **2026-11-04 起原生 SwiftUI 版已移除**，现行实现是 `desktop/`（Tauri + React），后端为 `src/admin_server.py`，见 README「管理 App」。下文保留第二版的页面设计与验收清单，其中 SwiftUI / Xcode / `scripts/build-app` 相关的构建说明已不适用。

更新：2026-11-03。状态：**第二版（五页）已实现，构建与界面检查通过；赎回抢购模式已实现（待实战）；设备、凭据和赎回窗口验收待账户持有人执行。**

当前开发分支：`codex/macos-admin-app`，尚未合并到 `main`，未推送。本文件记录当前实现和剩余验收；旧的“状态 / 系统 / 布防 / 设置”四页方案已被本版替换。

接手先读 `README.md`、`AGENT_WORKFLOW.md` §0、§1、§7、§9。真实提交、布防、撤单与凭据写入由账户持有人操作；Agent 不执行这些验收动作。

## 已完成

| 部分 | 当前实现 |
|---|---|
| 前台 App | AppKit 原生窗口承载 SwiftUI，最低 macOS 13，自用本机签名，无第三方 Swift 依赖 |
| 导航 | 左侧栏五项排在一起：任务、状态、演练、历史、设置；设置不再单独钉在底部 |
| 样式 | 纯深灰背景 `#1E1E1E`，无描边卡片 `#292929`；保留系统原生圆角、阴影和红绿灯；可点击控件手型指针 |
| 窗口行为 | 显示 Dock 图标，无菜单栏状态图标；红色关闭按钮与 Cmd-W 只隐藏窗口，Dock 点击重新打开，Dock“退出”或 Cmd-Q 才结束 App，无二次确认，退出不主动取消独立值守；窗口大小与当前页会记住 |
| 布局 | 页面统一保留底部 26pt 内容留白；任务页三张竖向模式卡按可用高度均分并铺满；状态页三行两列 Dashboard 同样按可用高度均分铺满；演练和历史使用滚动区域 |
| 任务页 | 首发、捡漏、赎回抢购三张竖向大卡；首发、赎回抢购可用并打开各自的布防表单，捡漏标“正在做” |
| 状态页 | 合并原状态与系统：值守、Mac、模拟器、画面、凭据与通知、最近日志六张卡片，三行两列按可用高度均分铺满；启停模拟器、恢复常亮、截图、休眠设置、复制监听指令都在卡片内；不再显示原来的“当前任务”卡 |
| 演练页 | 演练布防、单笔购买演练、设备操作、撤单（查看可撤单 / 撤单演练 / 真实撤单）、常用命令和命令输出 sheet |
| 历史页 | 全部历史记录（最多 1000 条）、完成统计、任务详情、全局值守日志；空记录时仍可打开日志 |
| 图标 | 红色圆徽、白色八爪鱼、镂空红眼和连接身体的横线；分层矢量源随工程构建 |
| Python 接口 | 单行 JSON；新增 `history --limit`、`log --lines`、`cancel`、`buy --dry-run`；原有布防、取消、恢复、凭据同步与 Agent 心跳保留 |
| 值守保护 | 版本 2 任务、文件锁、原子写、心跳、提交标记、任务和运行代次、恢复预算及终态历史 |
| 项目 Skill | 仅在项目 `skills/cmb-watch/SKILL.md`；复制指令生成当前项目的绝对路径，不使用 Claude 目录或全局安装 |
| 文档与测试 | README、执行手册及隔离测试已同步；验证详情见下文 |

## 架构与构建

```text
CMBFinanceBot.app
 ├─ CMBFinanceBotApp.swift  AppKit 窗口、菜单、Dock 唤起与退出
 ├─ Model.swift             状态、历史、日志、动作与轮询
 ├─ ManagementView.swift    五页导航、页头、错误条与单调度器
 ├─ TasksView.swift         三种模式卡
 ├─ ArmSheet.swift          布防表单与确认步骤
 ├─ DashboardView.swift     值守 / Mac / 模拟器 / 画面 / 凭据 / 日志
 ├─ DrillView.swift         演练命令、撤单与输出 sheet
 ├─ HistoryView.swift       历史列表、详情与日志
 ├─ SettingsView.swift      项目、Python 与凭据
 ├─ Theme.swift             配色、卡片、按钮、手型指针与格式化
 ├─ Backend.swift           Process + stdin / stdout / stderr
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
- `Backend.run` 在选定项目目录下运行 CLI。敏感值只用 stdin JSON，stdout/stderr 并行排空，错误只展示后端文案；一般超时 30 秒，启动模拟器 60 秒，单笔演练 120 秒，撤单 300 秒。
- App 不直接访问 ADB 或钥匙串。凭据仍由 Python 写到现有条目，回读验证；App 只展示配置状态。
- 当前页和窗口 frame 保存在 `UserDefaults`；关闭窗口只隐藏，重新打开保留页面。

## 五个页面

### 任务

三张竖向卡片按可用高度均分，刚好铺满窗口。首发、赎回抢购两张卡各自有“新建布防”，活动中的那张显示任务摘要和“刷新 / 取消布防”，另一张标“其他值守中”并禁用新建。捡漏仍显示“正在做”、规划文案和禁用按钮。

布防表单是 sheet，按模式区分：产品代码、金额、提前分钟数、演练开关和“立即排练”两边相同；首发用“开售时间”，赎回抢购用“额度放出时间”并多一个“窗口 N 分钟”（1–60，默认 3）。赎回抢购的卡还提示“窗口内反复打开购买页；出现购买表单才提交，没有额度不提交”。点布防后按钮进入 loading 并显示当前步骤；如果失败原因是模拟器没运行，App 会自动调用 `emulator start`（复用仍在运行的 adb 服务），开机后再按原参数自动布防一次，启动失败才把错误留在表单。产品/金额/时间由 App 先做格式校验，最终仍由 Python 校验。新建布防默认真实模式，需要再次输入金额；演练需手动打开，立即排练只能演练。取消布防有二次确认；`waiting`（盯盘中）显示为独立阶段，和“准备中”区分。

### 状态

一屏 Dashboard，三行两列；每行按可用高度均分，和任务页一样铺满：

- 值守：阶段、最近心跳、Agent、日志行数、值守进程；刷新和复制监听指令。
- Mac：电源、合盖、防休眠、网络耗时；刷新和休眠设置 sheet。
- 模拟器：运行、开机、App 进程、屏幕、插电常亮、锁屏禁用；启动/关闭/恢复常亮/截图/详情。
- 画面：最近截图预览，可放大。
- 凭据与通知：登录与交易凭据状态、邮件配置；打开设置。
- 最近日志：最近 6 行，可打开完整日志 sheet。

原来的“当前任务”卡被移除；活动任务的产品、金额、时间只在任务页出现。活动任务 `armed / preparing / firing` 期间禁止启动/关闭模拟器；进入提交后进程退出时，值守卡提示先查交易记录，不补单、不重试。

### 演练

- 演练布防：打开 `ArmSheet(drill: true)`，只走演练。
- 单笔购买：产品代码 + 金额，默认 `buy --dry-run`；开启「实际付款」并再次输入金额确认后调用 `buy --confirm-real-payment`，立即购买一笔，不创建值守任务。
- 设备操作：启动/关闭模拟器、恢复常亮、截图、刷新设备。
- 撤单：订单金额、最多笔数或全部；查看可撤单、撤单演练、真实撤单。真实撤单必须二次确认；值守活动期间全部禁用。
- 常用命令：`night_watch status/disarm`、`cancel_orders --list`、`fast_buy_uia2 --dry-run` 的等价入口，可复制。
- 命令输出：撤单/演练命令的文本输出放在 sheet 中，不再挤占页面底部。

### 历史

顶部统计总记录、已完成、已中止、已取消和演练数。左侧全部历史记录，右侧任务详情：开售/布防/结束/提交时间、阶段、结果、恢复记录。底部展示全局 `watch.log` 最近 200 行，可刷新、复制或打开文件；完整日志 sheet 可查看最近 800 行。没有历史记录时，详情区仍提供“查看值守日志”。

历史只包含版本 2 任务写入的终态记录；更早的版本 1 任务没有写入 `history.jsonl`。同一次布防恢复后可能留下多条记录，不代表新增购买。日志是全局的，不按任务拆分。

### 设置

项目目录、Python 路径、凭据配置状态和邮件是否配置集中显示。

九宫格选择 4–9 个不重复点，画两次一致后保存。交易密码使用当前、新值和确认三个安全输入框，由 Python 核对当前值并校验新值。设置仅同步脚本保存的凭据，不修改银行 App 的设置。准备/提交阶段和操作忙碌时禁用修改，离开设置清空输入。

### 刷新与通知

App 只有一个 5 秒调度器，窗口隐藏时降为 30 秒；进入页面时按页面加载数据（状态页读 `status/device/system`，历史页读 `history/log`）。阶段变化尝试发送系统通知，仍需验收系统授权与实际送达。

## Python CLI

每个业务命令向 stdout 输出一行 JSON。成功 `ok: true`、退出码 0；失败 `ok: false`、中文 `error`、退出码 1。无需 `--json`。

| 命令 | 行为 |
|---|---|
| `status` | 任务、日志、进程与双心跳；不调 ADB。配置状态会检查钥匙串，但不返回凭据值，可能触发系统授权 |
| `device` | 设备/模拟器状态，ADB 单次超时五秒，并行读取 |
| `system` | 电源、合盖、防休眠、网络等只读检查 |
| `history [--limit N]` | 终态记录，默认全部（最多 1000 条），按时间倒序；忽略不完整 JSON 行；返回总数和日志路径 |
| `log [--lines N]` | `watch.log` 最近 N 行（1–5000），返回路径、总行数和是否存在 |
| `emulator start / stop` | 项目模拟器启停；启动后等待开机并恢复常亮；活动任务禁止 stop |
| `keep-awake` | 恢复项目模拟器常亮 |
| `screenshot` | 返回项目截图路径，不向外发送 |
| `arm --code --amount (--at / --now) --prep-minutes [--dry-run]` | 经原逻辑布防，后台进程独立运行；admin CLI 的 `--now` 必须同时演练 |
| `disarm` | 提交阶段拒绝，准备阶段仍可取消 |
| `resume --reason [--session] [--kill-stale] [--after-manual-login]` | 按原任务恢复，不修改产品、金额、时间或图案预算 |
| `cancel [--amount] [--limit] [--list / --dry-run / --yes]` | 包装 `cancel_orders.py`；活动任务期间拒绝；`--list` 只列，`--dry-run` 到密码面板即停，真实撤单必须 `--yes` |
| `buy --code --amount (--dry-run / --confirm-real-payment)` | 包装 `fast_buy_uia2.py`，显式选择演练或真实单笔购买；活动任务期间拒绝；返回文本输出和结果 |
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
- `cancel` 与 `buy` 在活动任务期间拒绝，并持有 `task.lock` 直到子进程结束；真实撤单需显式确认。

## Agent 监听

规则唯一实现为 `skills/cmb-watch/SKILL.md`。App 复制的指令类似：

```text
读取项目 Skill「/绝对项目路径/skills/cmb-watch/SKILL.md」，用 cmb-watch 监听当前布防。
```

开始监听需用户要求。Skill 约定故障检测、双心跳、提交前恢复、取消/手动登录的逐次授权以及结束清理。相同状态保持安静；只有故障、恢复、结果或需要用户操作时通知。

App 不托管 Agent，也不保证某个环境具有 Monitor、手机通知或持续运行能力。缺少这些工具时必须说明限制，不能声称已经整夜监听。通知渠道依用户授权，不自动向其他人发送。

## 验证结果

### 已通过

- 相关 Python 测试 64 项：

  ```sh
  python3 -B -m unittest tests.test_night_watch tests.test_watch_recovery tests.test_admin_cli tests.test_amount tests.test_open_form
  ```

  覆盖旧流程、恢复拒绝条件、文件锁、两进程竞争、旧代次写回、提交标记、图案预算、手动登录路径、心跳、凭据 argv/stdin 边界、系统输出解析，以及历史、日志、撤单和单笔演练命令。

- Swift 桥接隔离测试：

  ```sh
  swiftc -parse-as-library -module-cache-path /tmp/cmb-swift-module-cache app/CMBFinanceBot/Backend.swift tests/BackendSmoke.swift -o /tmp/cmb-backend-smoke
  /tmp/cmb-backend-smoke
  ```

  验证 JSON、stdin、较大 stderr 不阻塞、非零退出错误。

- Release 构建、`codesign --verify --deep --strict`、Skill 格式校验和 `git diff --check`。
- 实际 UI 检查：五页导航；任务页三张竖向卡片按高度铺满；状态页一屏 Dashboard 六卡无裁切；演练页两个命令区与输出 sheet；历史页空态和日志入口；设置页保持原样；底部 26pt 留白；窗口关闭/重开、页面记忆和 Dock 唤起。已查看原生红绿灯无遮挡、系统圆角、滚动条最右侧和手型指针。
- 用独立的一秒测试进程确认 caffeinate 独立进程组；这不是完整设备值守验收。

### 已知限制

- 全量 `unittest discover` 有既有错误：废弃 `test_timed_buy.test_single_submit_success` 的数字键测试失败（执行手册 §8 已记录），本次不修改该路径。
- 当前系统 Python 的 urllib3/LibreSSL 警告仍存在，不影响上述隔离测试通过。
- 历史只从版本 2 任务开始；更早的版本 1 任务（包括 2026-11-03 已完成的旧任务）没有写入 `history.jsonl`，历史页可能为空。日志是全局 `watch.log`，不按任务拆分。
- 未实现捡漏模式、登录启动开关、远程 UI、签名公证；锁屏检测仍返回“无法读取”。赎回抢购已实现（脚本与管理 App），但尚未在真实 00:15 窗口里跑过。
- 监听 Skill 已落地，但没有运行真实整夜监听、手机通知或恢复故障注入验收。
- App 内真实撤单、单笔演练和模拟器操作尚未由账户持有人在新 UI 上实机验收；Agent 不执行这些动作。

## 下一步验收（账户持有人执行）

1. 在 App 设置里确认项目路径和 Python；检查五页导航、任务卡、状态 Dashboard、演练、历史和设置的加载。
2. 在演练页点“演练布防”，或在任务页“新建布防”表单里手动打开演练开关，检查启动准备、到密码页停止、取消布防确认和历史记录；中途退出 App 再重开，确认值守独立运行、当前页记忆符合预期。
3. 持有人亲自同步图案和交易密码，再在自己的终端演练验证回读；检查日志、进程参数和通知不含凭据。
4. 在演练页检查“查看可撤单”和“撤单演练”；真实撤单只在有测试单时由持有人确认执行，并先查交易记录。
5. 恢复故障演练使用至少十五分钟后的开售时间、`--prep-minutes 5 --dry-run`。不要用只剩三分钟的 `--now` 验证五分钟心跳超时。验证进程退出、卡住、模拟器退出、最多两次恢复、手动登录，以及 `fired_at` 后一律拒绝恢复。
6. 新 Agent 会话读取项目 Skill 后监听演练，检查心跳、失联提示、可用通知渠道和结束释放。工具能力不足时记录具体限制。
7. 做完以上检查后再考虑真实布防；保留最终以银行交易记录为准的核对流程。

窗口生命周期更新（2026-11-03）：按用户要求取消退出二次确认。红色关闭按钮和 Cmd-W 只隐藏窗口并保留 App 进程；Dock 点击恢复窗口，Dock“退出”或 Cmd-Q 直接退出。关闭设置窗口时卸载敏感输入视图并清空输入，重新打开设置时不恢复凭据输入。布防表单和后台值守不因关闭管理窗口而被取消。

本轮验证：Release 构建、签名和 diff 检查通过；实际点击红色关闭按钮后进程 PID 不变、App 仍运行，重新激活后恢复窗口，没有退出确认弹窗。

最终收尾（2026-11-03）：五页布局、任务页竖向铺满、状态页三行两列铺满、新建布防默认真实模式、演练输出 sheet 和历史日志均已完成；64 项测试、Release 构建、签名和 `git diff --check` 通过，App 已重启检查。真实设备、撤单和凭据验收仍待账户持有人执行。
