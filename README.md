# 自用招行理财脚本

在本机 Android 模拟器里运行招商银行 App，按指定的产品、金额和时间自动买理财。只供账户持有人自己使用。

> 这是个人自动化脚本，不是银行接口，也不绕过任何安全机制：所有操作都和手动点 App 一样走界面，一笔只提交一次。结果以银行交易记录和产品管理机构的确认为准。

## 模式

| 模式 | 状态 | 一句话 |
|---|---|---|
| 首发模式 | ✅ 已实战 | 9:00 准点抢一只新发理财 |
| 捡漏模式 | 📝 规划中 | 白天轮询多只理财，有人撤单就买 |
| 赎回抢购模式 | 📝 规划中 | 00:15 盯住一只理财，等赎回额度放出就买 |

### 首发模式（已实现）

**背景**：招行 App 一般在 9:00 准时放出首发理财，额度通常 5 秒内就被抢完。为了避开 9:00 整点可能出现的问题，在开售后 200ms 提交。如果碰上网络超时，基本无能为力。

**行为**：

- 开售时间默认 9:00，每次只买一只理财，金额固定。
- 开售前 15 分钟冷启动 App 并自动登录（九宫格），然后打开详情页预热会话和网络。
- 开售 +200ms 用 App 链接直接打开**购买页**：表单出现 → 风险弹窗 → 输入交易密码 → 确定，只提交一次。
- 表单 5 秒没出现或出现报错页就重开，最多 60 秒；只接受产品代码匹配、金额一致的表单，对不上就停止，不改金额。

**验证情况**：已在真实开售中跑通：开售前冷启动后九宫格第 1 次登录成功；开售 +200ms 打开购买页，约 4 秒完成提交，结果页显示"您的交易委托已接受"。此前用 0.01 元做过 10 次真实测试，全部成功，平均 5.24 秒。

**命令**（在自己的终端运行，正式布防请用 Terminal.app）：

```sh
python3 -B src/night_watch.py arm --code <产品代码> --amount <金额> --at 2026-11-04T09:00:00
python3 -B src/night_watch.py status
python3 -B src/night_watch.py disarm
```

`--at` 填开售时间，200ms 由脚本自动加。第一次用某个产品时，先加 `--dry-run` 演练。

### 捡漏模式（规划中）

**背景**：9:00 首发额度抢完后，当天 17:00 前如果有人撤单，额度会重新放出，还有机会捡漏。

**设想**：

- 没有固定时间，立即启动；默认运行 1 小时，可设置终止时间。
- 支持多只理财，在各自的购买页之间轮流查看是否可购买，可以买就买入。
- 金额为当前理财余额（可购额度）的 X%，且不超过 Y 元。

### 赎回抢购模式（规划中）

**背景**：有人赎回到账后，赎回的额度会在 00:15 放出，但不准时，可能延迟几秒，所以要一直刷新页面看有没有余额。

**设想**：

- 开始时间默认 00:15，每次只盯一只理财；开始前 15 分钟冷启动 App 并登录。
- 在目标购买页里反复查看是否可购买，可以买就买入；默认运行 3 分钟，可设置终止时间。
- 金额为当前理财余额（可购额度）的 X%，且不超过 Y 元。

## 能力

| 能力 | 说明 | 入口 |
|---|---|---|
| 值守布防 | 定时冷启动、登录、预热、到点提交；状态机防重复提交；夜里看护模拟器 | `src/night_watch.py` |
| 单笔购买 | 立即或定时买一笔，可 dry-run | `src/fast_buy_uia2.py` |
| 连续购买测速 | 连续 N 笔 0.01 元，逐步计时 | `src/buy_timed.py` |
| 批量撤单 | 从交易记录逐笔撤销可撤单的订单 | `src/cancel_orders.py` |
| 自动登录 | 九宫格图案存在 macOS 钥匙串，最多试 3 次防锁定 | `src/secure_input.py`、`src/keychain_store.py` |
| 邮件通知 | 可选，QQ 邮箱 SMTP，只发时间线和状态 | `src/notify.py` |
| 模拟器管理 | 启动 / 停止 / 状态、截图 | `scripts/project`、`scripts/capture` |

所有会提交的流程都支持 `--dry-run`：只走到密码页，不输密码、不提交。

## 架构

```
 Mac (caffeinate 防休眠)
 ├─ night_watch.py ── 调度与状态机：armed → preparing → firing → done
 │     │                状态写在 var/night/task.json，进程重启也不会重复提交
 │     ├─ manage.py ─────────── 项目专用模拟器与 ADB（端口 15554 / 15039）
 │     ├─ secure_input.py ───── 九宫格登录（图案取自 macOS 钥匙串）
 │     ├─ fast_buy_uia2.py ──── 打开购买页 → 表单 → 风险弹窗 → 密码 → 确定
 │     └─ notify.py ─────────── 邮件通知（可选）
 │
 └─ Android 模拟器 (Google APIs arm64, 320×640)
       └─ 招行 App
            ├─ cmbmobilebank:// 链接 ── 直接打开详情页 / 购买页
            ├─ UiAutomator2 ─────────── 读控件树（约 0.11 秒/次）、点击
            └─ WebView CDP ──────────── 确认前台页面的产品代码、执行页面脚本
```

几个关键设计：

- **App 链接直达购买页**。招行 App 注册了 `cmbmobilebank://`，用它打开 H5 购买页，表单 0.7 秒左右就能出现，省掉首页 → 理财 → 详情 → 购买的点击。开售前打开会被服务器拒绝，所以到点才打开，失败就重开。
- **控件树优先于截图**。用 UiAutomator2 读控件树判断页面和定位按钮；系统自带的 `uiautomator dump` 在有动画的页面上会失败，只作兜底。按文字定位元素，不用固定坐标。
- **双重校验**。控件树看不出是哪个产品，所以再用 CDP 读前台 WebView 地址里的产品代码；金额解析成数值比较（`￥5,000.00` = 5000）。
- **一笔只提交一次**。进入提交前先把状态写成 `firing`；结果不明时停下等人工查交易记录，绝不重试。
- **不重放接口**。购买接口有 TLS 固定、签名和一次性 token，重放既违反协议也可能触发风控。

## 目录

```
scripts/project      模拟器启动 / 停止 / 状态 / 创建虚拟设备
scripts/capture      截取当前模拟器画面到 var/screenshots/current.png
src/                 代码（见上方"能力"）
tests/               单元测试
config/example.json  交易配置示例（不含密码）
AGENT_WORKFLOW.md    操作手册：每个流程的步骤、日志含义、失败处理和技术结论
var/                 SDK、虚拟设备、日志、运行状态（Git 忽略，含账户数据）
```

`src/run_task.py`、`src/timed_buy.py` 是早期实验路径，已不再使用；`src/stress_buy.py` 是真实压测，慎用。

## 环境准备

需要 macOS Apple Silicon、Python 3、Java 17+，以及 Google 官方 Android SDK 命令行工具。可以把 JDK 放在 `var/amazon-corretto-21.jdk`，无须装到系统。

1. 从 [Android Studio 官方下载页](https://developer.android.com/studio)下载 Mac ARM 的 Command line tools，把压缩包里 `cmdline-tools` 的内容放到 `var/android-sdk/cmdline-tools/latest/`（确保有 `bin/sdkmanager`）。也可以设置 `ANDROID_SDK_ROOT` 使用已有 SDK。
2. 接受许可并安装组件、创建虚拟设备：

   ```sh
   export ANDROID_SDK_ROOT="$PWD/var/android-sdk"
   export JAVA_HOME="$PWD/var/amazon-corretto-21.jdk/Contents/Home"
   "$ANDROID_SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" --sdk_root="$ANDROID_SDK_ROOT" --licenses
   "$ANDROID_SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" --sdk_root="$ANDROID_SDK_ROOT" 'platform-tools' 'emulator' 'system-images;android-35;google_apis;arm64-v8a'
   ./scripts/project create-avd
   ```

3. `./scripts/project start` 启动，`status` 查看，`stop` 关闭。模拟器用端口 15554/15555，专用 ADB 服务用 15039，端口被占用时不会启动；不碰其他 ADB 服务或模拟器。日志在 `var/emulator.log`。
4. 在模拟器里安装招行 App 并手动登录一次，然后把凭据存进 macOS 钥匙串：
   - 首次：在 `config/credentials.json` 写入 `{"login_pattern": "<九宫格点位编号>", "payment_password": "<6 位交易密码>"}`，权限设为 `chmod 600`，再运行 `python3 src/keychain_store.py`。写入钥匙串并回读验证后，明文文件会被删除。
   - 以后改九宫格图案：`python3 src/keychain_store.py update-login`（不改交易密码）。
   - 可选的邮件通知：`python3 src/notify.py setup`，输入 QQ 邮箱的 SMTP 授权码。

   这些只改项目的钥匙串条目，不改银行 App 里的设置。

5. 跑测试：`python3 -B -m unittest tests.test_night_watch`

SDK 和虚拟设备体积较大，迁移到新机器后建议重新创建虚拟设备。

## 使用须知

- **真实提交、撤单、布防、写凭据**都由账户持有人在自己的终端运行。Agent 只做状态检查、截图、读日志和 `--dry-run`。
- **Mac 必须接电源**。值守包在 `caffeinate -dimsu` 里，但用电池时合盖仍会睡眠。
- **正式布防用 Terminal.app**，不要从会被重启的应用（如 Claude App）里的终端启动。
- **结果不明先查交易记录**，不要补单、不要重试。
- **测试单记得撤单**：定时开售的产品在详情页写着"××前可撤单"。
- **不要分享 `var/`**：里面有截图、日志和模拟器数据，可能含账户和资产信息。不要把密码写进配置、日志或聊天。

详细步骤、日志含义和排错见 [`AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md)。
