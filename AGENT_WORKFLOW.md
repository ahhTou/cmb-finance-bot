# Agent 执行手册

最后更新：2026-11-03。

这是本项目的操作手册。接手时先读 §0 和 §1，再按要做的事跳到对应流程：

| 要做的事 | 看哪节 | 主要命令 |
|---|---|---|
| 睡前布防，到点自动买 | §3 流程 A：完整值守购买 | `src/night_watch.py arm` |
| 现在买一笔 / 测速 / 演练 | §4 流程 B：单独购买测试 | `src/fast_buy_uia2.py`、`src/buy_timed.py` |
| 撤掉测试订单 | §5 流程 C：撤单 | `src/cancel_orders.py` |

所有命令都在项目根目录运行：

```sh
cd /Users/ahhtou/Dev/cmb-finance-bot
```

## 0. 谁来执行

- **账户持有人在自己的终端执行**：
  - 真实提交（购买、撤单）；
  - 布防值守（值守会自动登录，正式布防还会真实提交）；
  - 写入或更新凭据（`keychain_store.py`、`notify.py setup`）。
- **Agent 可以做**：
  - 状态检查、截图、读日志、`--list`；
  - `--dry-run`：只到密码页或密码面板，不输入密码、不提交；
  - 准备页面、改代码、写文档。
- **一笔交易只提交一次。** 结果不明时先查交易记录，绝不补单、不重试。

## 1. 当前状态

- **首发模式已在真实开售中验证**：开售前 15 分钟冷启动，九宫格第 1 次登录成功，准备约 18 秒；开售 +200ms 用 App 链接直接打开购买页，核心流程约 4 秒。
  - 定时开售产品的结果页文字是"您的交易委托已接受"，不是"提交成功"。脚本已把它算作成功结果。
- **值守排练都已跑通**：冷启动登录、deep link 打开详情页、`--prep-minutes 5`、`arm --now`，提交核心流程 3.4–3.5 秒。
- **锁屏不影响值守**：锁屏下登录和打开详情页都正常。但 Wi-Fi 外网时断时续时，表单可能在等待时间内出不来，值守会按设计停止。
- **正式布防要在 Terminal.app 里运行**：从 Claude App 终端启动的值守，会在 Claude App 重启时被一起结束。
- **测试单要撤掉**：排练和测试会留下 0.01 元订单，按流程 C 在可撤单截止时间前撤掉。
- 模拟器配置已提高到 6 核 / 4 GB / SwiftShader，冷启动约 20 秒。原配置备份在 `var/config.ini.bak-*`。
- 屏幕常亮已设置：
  - `stay_on_while_plugged_in=15`，模拟 AC 充电；
  - `screen_off_timeout` 设为最大值；
  - `locksettings` 已禁用。

  其中常亮和 AC 两项在**模拟器重启后会丢失**。值守重启模拟器后会自动恢复；手动重启后要按 §2 重新设置。
- 全屏打开详情页（首页 → 理财 → 跳转）：修复后已在真机上跑通，从"我的"页开始约 7.3 秒；还没在值守里完整跑过。

## 2. 通用前置检查（任何流程开始前都做）

```sh
./scripts/project status                     # adb / emulator 都应为“运行中”
./scripts/project start                      # 未运行时启动；约 20 秒开机
./scripts/capture                            # 截图 → var/screenshots/current.png
```

```sh
A="var/android-sdk/platform-tools/adb -P 15039 -s emulator-15554"
$A shell getprop sys.boot_completed           # 1 = 开机完成
$A shell pidof cmb.pb                         # 有输出 = App 在运行
$A shell dumpsys power | grep -E 'mWakefulness|mStayOn'   # Awake / true
```

在 zsh 里 `$A` 不会按空格拆开，需要写成 `${=A}`，或者直接写全路径。

模拟器重启后，恢复常亮设置：

```sh
var/android-sdk/platform-tools/adb -P 15039 -s emulator-15554 shell settings put global stay_on_while_plugged_in 15
var/android-sdk/platform-tools/adb -P 15039 -s emulator-15554 shell dumpsys battery set ac 1
```

几点注意：
- **只用项目自己的 ADB**：端口 15039，设备 `emulator-15554`。不要运行系统默认的 `adb`，它会在 5037 端口另起一个服务。
- **判断是否已登录**：先进"我的"页面。能正常截图 = 已登录；截图全黑或停在九宫格页 = 未登录。首页能看到账户信息**不能**当作已登录的证据。
- **iOS 模拟器工具不适用**，这里是 Android 模拟器。

## 3. 流程 A：完整值守购买（`src/night_watch.py`）

### 3.1 时间线

| 时间 | 值守做什么 |
|---|---|
| 布防时 | 强制关闭 App，之后整夜不碰它 |
| 夜里 | 每 2 分钟检查一次模拟器开机状态和屏幕。连续 3 次失败就重启模拟器 |
| 开售前 15 分钟 | 冷启动 App → 点"我的" → 已登录就跳过，在九宫格页就输入图案。失败就强制关闭 App 重来，**最多输入 3 次图案**，最多冷启动 5 次 |
| 登录后 | 用 App 链接打开详情页，只作预热（会话、网络）；打不开只记日志，不影响开售（见 §6.2） |
| 开售前 1 分钟 | 只看 App 进程还在，**不重新登录、不重启、不点击** |
| 开售 + 200ms | 调用 `fast_buy_uia2.run()`：App 链接直接打开购买页（慢了或报错就重开）→ 表单 → 风险弹窗 → 密码 → 确定，**只提交一次** |

几条防护：
- 状态在调用 `run()` **之前**就写成 `firing`，所以值守进程重启后不会再提交第二次。
- 图案已输入的次数存在 `var/night/task.json`，进程重启后接着累计，不会清零。
- 整个进程包在 `caffeinate -dimsu` 里防止 Mac 休眠。**Mac 必须接电源**，用电池时合盖仍会睡眠。

### 3.2 睡前步骤（账户持有人执行）

1. 做一遍 §2 的检查：模拟器在运行、屏幕常亮。App 开着也没关系，布防时会自动关掉。
2. 布防。`--at` 填**开售时间**，200ms 由脚本自动加。开售时间必须带日期，而且要在 17 分钟到 24 小时之后：

   ```sh
   python3 -B src/night_watch.py arm --code <产品代码> --amount <金额> --at YYYY-MM-DDT09:00:00
   ```

   想尽快看排练效果时，加 `--prep-minutes 5`（范围 5–15，默认 15）：开售前 5 分钟才冷启动，开售时间最少只需在 7 分钟之后。正式值守保持默认 15，失败时重试的余地更大。

   第一次用某个产品时，先加 `--dry-run` 演练。演练只走到密码页，然后关闭密码框，不输密码、不提交。

3. 确认值守进程在运行：

   ```sh
   python3 -B src/night_watch.py status       # 进程：运行中；阶段：armed
   ```

4. 邮件通知是可选的。在自己的终端运行 `python3 src/notify.py setup` 配置 QQ 邮箱的 SMTP 授权码。不配置的话，所有通知只写进日志。另一种方式：让 Agent 会话盯着日志，通过 Gmail 转发通知，但这要求 Claude 桌面 App 整夜开着。

### 3.3 查看与取消

```sh
python3 -B src/night_watch.py status          # 任务、阶段、已输入图案次数、最近 8 行日志
python3 -B src/night_watch.py disarm          # 取消（阶段为 firing 时拒绝）
tail -f var/night/watch.log                   # 完整日志
```

阶段依次为：`armed` → `preparing` → `firing` → `done`。如果中途出错，阶段会变成 `aborted`；手动取消则是 `disarmed`。

### 3.4 早上检查

1. `status` 看最终阶段和结果：
   - `done` 且结果为"提交成功 / 购买成功"：去 App 的交易记录核对。以产品管理机构的确认为准。
   - 其他情况：按 §3.5 处理。
2. 无论结果如何，**都以银行交易记录为准**。

### 3.5 日志信息与处理

| 日志 / 状态 | 含义 | 处理 |
|---|---|---|
| `已输入图案 3 次仍未登录` | 自动登录失败，已停下以免锁定 | 手动登录。不要马上重新布防，否则次数清零后又会试 3 次 |
| `冷启动后 40 秒内没有找到“我的”` | App 没启动起来，或界面变了 | 截图看实际界面 |
| `既不是登录页也不是已登录` | 进"我的"后出现了未知页面（比如弹窗） | 截图确认，必要时更新 `night_watch.py` 里的识别规则 |
| `全屏打开失败，改为在内嵌 WebView 里直跳` | 首页 → 理财 没走通，已改为在内嵌 WebView 里跳转 | 不影响 `goBuy()`（22:47 排练就是这样成功的）。事后截图查看首页或理财入口有没有变化 |
| `没有可用的 WebView` / `直跳后详情页没有出现` | 两种跳转方式都失败了 | 见 §6.2；可以手动打开详情页后改用流程 B |
| `准备阶段一直没有成功` | 到开售前 1 分钟仍没准备好 | 这次不会提交 |
| `购买流程中途停止` | `run()` 报错 | **先查交易记录，不要重试** |
| `结果需要人工确认` | 提交后没认出结果页 | **先查交易记录，不要重试** |
| 阶段卡在 `firing`、进程不在 | 提交过程中进程被杀 | 先查交易记录，再删除 `var/night/task.json` 才能重新布防 |
| `模拟器已自动重启` | 夜里模拟器挂了 | 值守已自动恢复常亮和 AC 设置，开售前 15 分钟照常冷启动登录 |

### 3.6 已知缺口

- 值守里用 deep link 打开详情页，23:28 排练已完整跑通。"首页 → 理财"全屏打开和内嵌跳转只作兜底。
- `goBuy()` 在开售时刻调用，页面是开售前加载的，页面里的状态还是旧的。银行客户经理也会直接发购买链接，`goBuy()` 只是模拟同样的行为。
- 定时开售的产品只实测过一次。不同产品的结果页、风险弹窗可能不一样，遇到没见过的页面时值守会停下，按 §3.5 处理。

## 4. 流程 B：单独购买测试

### 4.1 准备：登录并打开详情页（全屏）

1. App 已登录（§2 的判断方法）。如果没登录，在自己的终端运行 `python3 src/secure_input.py login`，或手动登录。
2. 打开详情页。`open_detail()` 优先用 App 链接打开；打不开时依次退回：首页 → 理财后跳转，再退回内嵌 WebView 跳转（见 §6.2）：

   ```sh
   python3 -B -c "import sys; sys.path.insert(0,'src'); import night_watch as nw; nw.open_detail('133045A')"
   ./scripts/capture                    # 截图确认详情页在前台
   ```

### 4.2 演练（Agent 可执行，不提交）

```sh
python3 -B src/fast_buy_uia2.py --code 133045A --amount 0.01 --dry-run
```

演练会走到密码页并输出耗时，不输密码、不提交。跑完把密码框关掉：

```sh
python3 -B -c "import sys; sys.path.insert(0,'src'); import fast_buy_uia2 as f; f.close_password_panel()"
```

### 4.3 真实购买（账户持有人执行）

```sh
python3 -B src/fast_buy_uia2.py --code 133045A --amount 0.01                                  # 立即执行
python3 -B src/fast_buy_uia2.py --code 133045A --amount 0.01 --at 2026-11-03T09:00:00.200     # 定时执行
python3 -B src/buy_timed.py --code 133045A --runs 3                                           # 连续 N 笔，并逐步计时
```

- 金额：正数，最多两位小数，上限 50000 元（`fast_buy.MAX_AMOUNT`，防止输错）。`buy_timed.py` 仍然只允许 0.01。
- `--at` 跨天必须带日期，目标时间已过会报错。用 `fast_buy_uia2.py` 定时执行时，要另外运行 `caffeinate -dimsu -t 900` 防止 Mac 休眠。
- `buy_timed.py` 每一笔开始前会自动关掉上一笔的结果页并重新跳转详情页。任何一笔结果不明或失败就停止。计时记录在 `var/buy_timed_log.jsonl`。
- 结果页显示"提交成功"只代表申请已受理，最终以产品管理机构的确认为准。
- 测试单记得按流程 C 撤掉。

## 5. 流程 C：撤单（`src/cancel_orders.py`）

已验证的路径：交易记录 → 点"可撤单" → 交易详情 → 点"撤单" → 密码面板 → 输入 6 位密码 → 完成 → 确定 → "您的撤单请求已受理" → 完成 → 回到交易记录。

1. **准备**：在 App 里打开"交易记录"，筛选条件设为"全部类型 / 进行中 / 近 1 年"。必须从 App 内的入口进入；用 CDP 直接加载交易记录列表时视口异常，只加载 10 条。
2. **先列出、再演练**（Agent 可执行）：

   ```sh
   python3 -B src/cancel_orders.py --list        # 只列出可撤单的订单
   python3 -B src/cancel_orders.py --dry-run     # 走到第一笔的密码面板，不输入密码
   ```

3. **撤单**（账户持有人执行）：

   ```sh
   python3 -B src/cancel_orders.py --limit 1     # 先撤一笔
   python3 -B src/cancel_orders.py               # 再撤剩下的全部（默认只处理 0.01 元）
   ```

4. **核对**：把筛选条件切到"全部"，确认每一笔都是"已撤单"。日志在 `var/cancel_log.jsonl`。

几条规则：
- 一次只撤一笔，确认列表数量减少后才撤下一笔。
- 详情页和密码面板都会核对金额。
- 6 位密码没全部输入就关闭面板，绝不点灰色的"确定"。
- 结果不明就停止，**不重试**。
- **截止时间**：以详情页显示的"××前可撤单"为准。133045A 当天的单是次日 17:00 前。

## 6. 关键技术结论

### 6.1 登录

- 九宫格使用慢速参数：起笔 0.30 秒、每步 0.07 秒、每个点停 0.25 秒，整套约 5.5–6.7 秒，多次成功（21:18、21:56）。图案存在钥匙串里。
- 登录前读九宫格页控件用值守的 `read_screen()`（uia2 优先），再把控件树传给 `secure_input.login(root=...)`。刚冷启动时系统 `uiautomator dump` 可能读不到（23:18 三次都失败）；读不到就重启 App，不计入图案次数。
- 输错的手势很可能计入锁定次数，所以**每晚最多试 3 次**，失败就停。
- 图案的坐标只适用于 320×640 分辨率；`secure_input.login()` 会先校验分辨率。

### 6.2 详情页直跳

- **首选：App 自己的链接（deep link）**。招行 App 注册了 `cmbmobilebank://`（入口是 `SchemeEntryActivity`），用标准的 Android VIEW intent 打开：

  ```sh
  adb shell am start -a android.intent.action.VIEW -d 'cmbmobilebank://cmbls/FunctionJump/?action=gourl&src=<URL 编码后的详情页地址>&closeCurrentView=false&needlogin=true' cmb.pb
  ```

  App 会先过一遍自己的登录检查（`PBLoginActivity`），然后**新开一个独立的 WebView**，打开正规的详情页，底部有"加自选 / 咨询 / 购买"按钮（开售前显示"11.03开售"）。这和招行生活 App、分享链接走的是同一个入口（详情页的 `jumpBuy` 源码里就有这段）。实测：133045A 约 9 秒（第一次），JX040229 约 0.6 秒（App 已在运行）；从这个页面 dry-run 5000 元到密码页 2.76 秒。另外 `https://cmbt.cn/...` 短链接也注册在同一个入口上。
- 下面两种是兜底方式，都是往已有的 WebView 里塞地址：

- 详情页地址如下，只需替换 `XRIPINN`：

  `https://mobile.cmbchina.com/IEntrustFinance/subsidiaryproduct/financedetail.html?XRIPINN=133045A&XSAACOD=D07&DeviceType=E&Version=14.4.8&SystemVersion=15&_u=24&appflag=1&_urlrefer=PLATFORM&behavior_entryid=ASC006002`

- **冷启动后没有全屏的 H5 页面**，只有首页和"我的"页里内嵌的 WebView。直接跳转只会把首页内嵌区域（y=310 起）的内容换成详情页，屏幕上看不到。不过 `goBuy()` 照样能打开购买表单（21:58 已验证），所以值守把它当作兜底。
- **点"首页"失败的原因**（22:47 排练）：系统自带的 `uiautomator dump` 要等页面静止，"我的"页上有动画一直不停，于是报 `could not get idle state`，读不到控件。值守现在改用 uia2 读控件树（没有这个限制），读不到时再退回系统 dump。底部标签的文字在 content-desc 里（"首页"、"理财"、"我的"），`tap_text()` 两处都会查。
- **全屏打开的方法**：点首页的"理财"，会打开一个全屏的 `tabfinprddefault.html`（screenY=0，其他 WebView 都变成不可见），再在这个页面里跳转。跳完后，页面控件树里有"购买，点击可跳转"和产品代码，和手动打开时一样。这个方法已实现在 `night_watch.open_detail()` 里。
- CDP 返回的 `visible` 标记**不可靠**：后台标签页里的 WebView 也会标成 visible。要判断哪个 WebView 在前台，看 `screenY` 和页面控件树。

### 6.3 goBuy 与金额参数

- 详情页 Vue 组件的 `goBuyParam.CurDepositBuyAmount` 是金额参数。设为 `"0.01"` 后调用 `goBuy()`，购买表单会直接带着 0.01 打开，省掉点"购买"和输入金额两步。
- 详情页在开售前就可以打开。`goBuy()` 应在**开售时刻（+200ms）调用一次**，不需要先刷新页面；开售前不要调用。
- `js_prefill_and_buy()` **只认产品代码完全匹配的详情页**，不会退而对其他产品下单。
- `goBuy` 的源码（JX040229，开售前读取）：根据产品类型选购买页地址，然后调用 `jumpBuy`，**不检查 `btnTag`**。开售前页面上已经有 `goBuy` 和 `goBuyParam`。
- **购买页地址**（23:04 截获 `goBuy` 的跳转参数得到）：`goBuy` → `jumpBuy` → `loginOk` → `$jumpWithUrl`，最终打开 H5 购买页：

  `https://mobile.cmbchina.com/IEntrustFinance/subsidiaryfinancing/saentrustbuy.html?SaaCod=D07&CodeInn=<代码>&FndInn=<代码>&CurDepositBuyAmount=<金额>&CommendCode=&PosSce=&refOrderNo=&refFrom=&videoChannel=&videoSerialID=&prodSeqNbr=&SubAccount=&PosTag=&AccountUID=`

  - 在全屏 WebView 里直接跳到这个地址，**0.71 秒**就能打开"理财购买"表单，金额也带进去了（133045A 实测）。不需要详情页，也不需要 `goBuy()`。
  - **开售前打开会被服务器拒绝**：JX040229 在 23:05 打开，页面提示"TOPI101W - 购买失败，当前时间不在产品交易开放期"。开售时间由银行服务器控制，和页面上的 `btnTag` 无关。
  - **现在的默认路径**（`fast_buy.open_buy_link()`）：用 App 链接 `cmbmobilebank://cmbls/FunctionJump/?action=gourl&src=<购买页地址>` 打开，App 新开一个购买页容器，并替换掉旧的。`fast_buy_uia2.open_form()` 每 0.08 秒读一次控件树：表单 5 秒没出现就重开；出现"购买失败 / TOPI / 系统繁忙"等报错页，1 秒后重开；60 秒后放弃。重开只发生在点"同意协议下一步"之前，不会重复下单。
  - **产品校验**：控件树看不出是哪个产品的表单，旧表单可能还在前台。所以还要用 CDP 确认前台 WebView 地址里的 `CodeInn` 是目标代码（`buy_page_shown()`）。表单金额对不上就停止，绝不改金额。
  - 00:42 实测：JX040229 开售前打开返回"TQH10IW / TOPI101W 当前时间不在产品交易开放期"，60 秒内重开 49 次后停止；133045A 从首页到密码页 2.75–4.80 秒（网络不稳时第 1 次超时、第 2 次成功）。
  - 旧路径（详情页 + `goBuy()`）保留为 `fast_buy_uia2.py --via-gobuy`。在详情页 WebView 里直接跳购买页不要用：密码框的关闭按钮会和标题栏的"…"重叠。
- **客户经理聊天页**（我的 → 账户总览下的客户经理卡片）会留下几个 228×305 的小 WebView，它们也"可见、顶端在 y=0"。所以全屏判断还要求宽度 ≥ 300、高度 ≥ 500，否则跳转会落进小卡片里。
- **密码页金额格式**：0.01 元显示为 `￥0.01`，5000 元显示为 `￥5,000.00`（带千分位）。脚本把页面上所有 ￥ 金额解析成数值再比较，所以 `￥5000` 不会误匹配 `￥50,000.00`。

### 6.4 风险弹窗与密码

- "一键输入"按钮在弹窗动画中会移动，必须按文字定位元素，不能用固定坐标。
- 不能用"屏幕全黑"来判断到了密码页：PDF 和协议查看器也是黑的，曾因此误报"已提交"。
- **只输入 5 位密码的根因**：密码面板刚滑入时，触摸层还没就绪，第一下点击会被吞掉。修复方法：
  1. 等键盘位置稳定后，连续输入 6 位并点"完成"；
  2. 检查"确定"有没有变成可用；
  3. 不可用就点输入框（会清空已输入的位数）重输一次；
  4. 仍不可用就关闭面板并停止，**绝不点灰色的"确定"**。

  撤单脚本更保守：等面板稳定 0.9 秒，每位间隔 0.10 秒。

### 6.5 速度

- UiAutomator2 已装在 `var/uia2`。读取一次页面控件树约 0.11 秒；连接加预热 0.7–1.3 秒，放在目标时间之前完成。
- 10 次 0.01 元真实测试：全部成功，平均 5.24 秒，最快 3.33 秒，最慢 6.74 秒。22:00 的演练到密码页约 2.89 秒。
- **不要承诺 3 秒内完成。** 也不要重放购买接口：有 TLS 固定、签名和一次性 token，还违反协议，可能触发风控。

## 7. 安全与边界

- 只操作项目模拟器 `emulator-15554` 和专用 ADB 端口 15039。不碰其他真机、其他模拟器，也不碰 Mac 上的其他进程。
- 凭据存在 macOS 钥匙串里。不读取、打印、转述或记录任何密码，也不把密码放进命令行、日志或聊天。
- 不重放接口，不绕过银行的安全机制。`goBuy()` 只在开售时刻对目标产品调用一次。
- 只有用户明确指定了产品、金额、时间，才发起真实交易。不要凭历史参数推测下一次交易。
- `var/` 目录里有账户数据、截图和模拟器数据，不分享，也不提交到 Git。
- 邮件和通知里只写时间线和状态，不放截图、余额或账户信息。

## 8. 文件索引

| 文件 | 作用 |
|---|---|
| `src/night_watch.py` | 夜间值守：`arm` / `status` / `disarm` / `run` |
| `src/notify.py` | 可选的 QQ 邮箱 SMTP 通知（`setup` / `test`） |
| `src/fast_buy_uia2.py` | 单笔购买（推荐），值守也调用它 |
| `src/buy_timed.py` | 连续 N 笔购买，带逐步计时；提供 `DETAIL_URL` 和 `js_eval_page` |
| `src/cancel_orders.py` | 批量撤单 |
| `src/fast_buy.py` | `goBuy()` 预填、等待目标时间等公共函数；UI-dump 版回退路径 |
| `src/secure_input.py` | 九宫格登录、页面控件树读取、截图判断 |
| `src/keychain_store.py` | 钥匙串读写（`update-login`） |
| `src/manage.py`、`scripts/project` | 模拟器启动 / 停止 / 状态 |
| `src/stress_buy.py` | N 笔真实购买压测，慎用 |
| `src/run_task.py`、`src/timed_buy.py` | 早期实验路径，已不再使用；`tests/test_timed_buy.py` 有 1 个报错 |
| `tests/test_night_watch.py` | 值守单元测试：`python3 -B -m unittest tests.test_night_watch` |
