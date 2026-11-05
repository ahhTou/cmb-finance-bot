# “跳过模拟密码输入”可行性调查

日期：2026-11-05。状态：已确认旧路径的公钥选择错误。修正后真实提交成功，现已接入管理 App 的「模拟密码输入」设置，默认关闭。

先做静态取证，后用用户指定的 `133045A / 0.01 元` 做不提交演练。以下保留静态阶段的证据和当时的未知项，最新结论见“演练与方法追踪”。

目标是在保留银行预检查、风险确认和一次提交约束的前提下，由受信任脚本在进程内读取钥匙串交易密码，转换为银行页面需要的 `pwd`，省去安全键盘动画和模拟点击。此次仅做静态取证，没有读取钥匙串、输入密码、布防或提交交易。

## 已确认的调用链

当前公开购买页加载 `saentrustbuy.5b669afa.min.js`、`chunk-ui.ebc92261.min.js` 和 `chunk-frame.cf0a63c2.min.js`。

```text
风险组件确认 → callPwd()
  → $pwdModal.show({ onConfirm: value => doBuy(value) })
  → 原生桥 openCMBKeyboard({ needEncrypt: true, encryptParam, ... })
  → success({ text, length, textHash })
  → 密码组件保存 text，length=6 时允许确认
  → onPwdModalConfirm() → onConfirm(text)
  → doBuy(text) → 下单参数 pwd: text
```

网页没有在 `doBuy` 中对密码做加密，使用的是原生安全键盘返回的 `text`。没有实际读取返回值，因此此处没有记录任何密码或交易密文。

- `$pwdModal.simulateInput(value, length)` 仅赋值 `simulateVal` / `simulateLen`，没有加密步骤。把明文传进去不能据此视为有效交易密文。
- `$pwdModal.getEncParam(transFactor)` 只准备 `encType / encRegexText / encFactor`，不接受明文密码，也不返回密码密文。
- 框架声明 `National=S`、`L4National=M`、`L4Info=I`、`L4AntiReplay=R` 等模式，按客户端版本和配置选择。防重放模式另有因子获取路径。这说明不能凭密码长度或通用算法名称推断转换方式。
- 本购买页调用的是 `show()`，不是 `showSafely()`。不能把其他分支支持动态因子直接当成本购买页已启用防重放的证据；当前运行时采用的模式未观测。
- 对已取得的网页桥接包装方法进行了检索，未找到供本链路使用的独立明文密码加密方法。包装方法的缺失不能证明客户端内部不存在该能力。

## APK 静态检索的范围

只读复制模拟器中 `cmb.pb` 的安装包，检查了 ZIP 成员、DEX 字符串及方法声明，没有读取应用私有目录。

- 发现 `com.unionpay.encrypt.IJniInterface.encryptPwdNSA` / `encryptPwdWithKeyNSA`，属于银联组件；没有证据连接到本理财安全键盘，不能直接使用。
- 没有在 DEX 明文字符串中定位到 `openCMBKeyboard` 对应实现。该检索不覆盖运行时动态加载、混淆字符串或 native 实现，不能据此判断功能不存在。
- 当前没有配置 REA 的 JADX 提供器；没有完成 Android 方法体反编译或原生库调用链分析。静态结果没有证明密文可离线生成，也没有证明一定不可以。

## 设置接入前仍需完成的验证

1. 定位原生 `openCMBKeyboard` 的实现及实际加密入口，确认输入参数、密钥/会话依赖、当前 `encType` 和输出格式。优先复用银行原组件，不自行猜算法、复用旧密文或重放购买请求。
2. 仅用虚构测试密码在隔离环境验证转换；阻断 `onConfirm / doBuy / entrustBuy` 等提交路径。不得以真实账户上的“试错下单”验证格式。
3. 明确明文从受信任脚本进入加密组件的通道，防止出现在 argv、CDP 调试日志、异常、前端状态或持久化文件中。页面只应收到交易所需的转换结果。
4. 转换失败即停止，不自动转成明文提交，也不回退后重复提交。演练应在转换成功后销毁结果并停止，不能触发确认回调。
5. 通过上述验证后再增加默认关闭的 `skip_simulated_password_input`（界面：“跳过模拟密码输入”），同步设置验证、API 类型、单笔购买、值守任务快照和配置摘要；已有任务按布防时快照执行。

当前没有添加空开关或改变购买路径。后续若必须执行读取真实凭据的演练，仍按 `AGENT_WORKFLOW.md` §0 获取该次明确确认。

## 补充：原生入口、依赖与候选方案

### 入口定位的实际进展

对同一 APK 的离线检查发现，关键代码载荷在 `lib/arm64-v8a/libdatajar.so`，并非普通 DEX。该 ELF 导出 `_binary_dexdata0_start / end / size`，数据段约 60MB。载荷中存在下列类描述符与源码文件名：

- `cmb.pb.app.cmblfunc.CMBKeyboardOpenService`，以及其内部类；同一载荷存在 `openCMBKeyboard`、`encryptParam`、`needEncrypt`、`encType`、`encFactor`、`encRegexText`。
- `cmb.pb.app.clientbasefunc.CommonKeyboardFunc`、`KeyboardFunc`。
- `com.pb.infrastructrue.cmbencrypt.*`、`com.pb.wbkey.innerkey.InnerWBEncryptKey`、`outerwbkey.OuterWBEncryptKey`、`pbkey.PBWBEncryptKey`。
- `com.cmbchina.channel.SMCryptKY`、`ISMCrypt`。
- 相关方法名线索包括 `getEncryptText`、`getEncryptData`、`getEncryptFactor`、`getEncryptFactorForNewType`、`setCMBKeyboardAPI`、`showCMBKeyboardWindow2`。

**边界**：这些是载荷中的静态名称，不是已恢复的调用图；不能把上述方法任意串成已证实的链路，也不能把白盒密钥类的存在当成安全键盘必用白盒密钥的证明。

临时取得官方 JADX 1.5.6 后，对普通 DEX 的调用者 `u1.k` 完成反编译，确认其包装了 `SMCryptKY.CMBSM2Encrypt`、`CMBSM4EncryptWithCBC`、`CMBSM3HMAC`。但它与键盘服务的关联仍未证实；`SMCryptKY` 自身的类定义不在这些普通 DEX 中，不能据此认定 `u1.k` 就是交易密码入口。

### 已知依赖与尚未确定的依赖

| 项目 | 证据与结论 |
|---|---|
| 网页默认加密模式 | 当前 frame 的模块 `839d` 内构建配置没有 `OWL_NEWCIPHER` 或 `OWL_ENABLE_ANTIREPLAY`；模块 `8414` 将两项初始化为 `false`，`4dd7.v()` 默认得到 `National=S`。这是静态初始化结论，未观测登录后的页面状态是否被改写。 |
| 网页初始加密参数 | 密码组件默认 `encRegexText=""`、`encFactor=""`；购买页的 `callPwd()` 调 `show()`，没有显式覆盖 `encryptParam`。 |
| 网页防重放分支 | `getEncParam()` 的 `R` 分支才调用框架模块 `9ab2.c.create(transFactor)`，其路径是 `/base/trans-mask/create`；该分支不能套用到当前购买页的默认 `show()` 路径。本次没有调用该接口。 |
| 登录会话与原生密钥 | 未确定。没有取得原生方法体，尚不知道 S 模式是否使用登录后装载的密钥、客户端环境对象、随机数或其他会话材料。不能由空 `encFactor` 推出“无会话依赖”。 |
| 键盘实例依赖 | 未确定。`getEncryptText` 等名称不能证明存在 `encrypt(plaintext)` 接口；也可能只对安全控件内部状态工作。 |
| 交易参数绑定及密文有效期 | 未确定。没有生成/保存/复用交易密文，也没有通过试错下单验证。 |

### 候选方案：优先在招行进程内复用原加密组件

先不选择“Mac 端自行实现 SM2/SM4”。候选数据路径为：

```text
受信任脚本进程内读取钥匙串
 → 受限、短生命周期的进程间通道
 → 招行进程内的原加密组件（使用当前环境与原模式）
 → 仅将转换结果交给当前购买流程
 → 原风险确认、交易参数复核及一次提交约束
```

这是一项架构选择，**入口可调用性尚未证明**。若原组件只允许通过内部键盘状态加密，或必须改动其安全输入机制才能注入明文，则不能承诺实现“完全不弹密码框”。届时应重新评估收益与维护成本，不以伪造长度、填入明文或复用旧密文代替。

方案定稿前的最小验证顺序：

1. 在隔离的无真实凭据环境中，恢复并检查 `CMBKeyboardOpenService` 的参数解析和最终加密调用；记录方法所属类、签名与调用顺序，不记录密钥值。
2. 用虚构测试输入确认：是否支持无键盘实例加密、需要哪些环境对象、是否触发网络请求；只记录参数名、类型和成功状态。
3. 对照未登录、登录后、重新登录、重新创建键盘/页面四种生命周期，确定哪些依赖必须当次获取。涉及真实登录/凭据的执行另按 §0 确认，不从历史任务继承授权。
4. 独立验证不提交演练的停止点：任何密文生成不能触发 `onConfirm / doBuy / entrustBuy`；生成后销毁，不以真实下单验证密码格式。
5. 只有确认可调用且支持无 UI 后，才进入设置和代码接入设计。

### 本轮执行边界与限制

本轮仅修改此调查文档，未改项目代码或购买配置。为检查代码加载情况曾启动 App，未登录、未读取钥匙串；结束时确认值守为 `disarmed` 并关闭本轮启动的 App，恢复调查前未运行状态。

只读代码映射确认加载了 `libdatajar.so` 与加固库。对已知安装包代码映射的首个页面、以及独立分配开头的 DEX 头进行了受限检查，没有导出可用 DEX；不匹配的分配内容未输出或保存。没有做全进程内存转储、修改 App、注入诊断代码或附加调试器。现有证据仍不足以确认最终方法签名或会话依赖，因此方案状态保持“候选”，不标记为可执行。

临时分析产物位于 `/private/tmp/cmb-native-plan/`，JADX 输出的普通 DEX 包装类为 `u1-k.java`。临时文件不作为长期依赖，后续以 APK 哈希重新取证。

## 演练与方法追踪：已定位 S 模式的原生加密链

测试产品与金额：`133045A / 0.01 元`。使用原登录和风险预检查流程。取证脚本在唯一匹配的购买表单上先阻断 `doBuy`、`entrustBuy`、`entrustOtherCardBuy`，并验证密码面板未启用 `autoSubmit`。只在原生安全键盘输入虚构数字，未点最终「确定」，未提交；没有向键盘输入真实交易密码。取证脚本位于临时目录，未修改项目代码。

- **未开启方法追踪的演练**完成了六位输入，密码面板正常关闭。运行时实测 `encType=S`、`encFactor` 与 `encRegexText` 均为空，键盘回传值长度为 230 个字符，提交尝试数为 0。仅记录模式、长度和状态，未导出密文或凭据。该次从已加载表单到输完约 2.34 秒。
- **开启方法追踪的样本**因追踪开销未完整输到六位，不能用于测速；记录到三次完整的转换与回调组装。提交保护未触发。追踪方法事件依据 [Android ART 的 streaming trace 格式](https://android.googlesource.com/platform/art/+/493bc1f83e72cd649963a555f17a642693c3c264/runtime/trace.cc#994) 按线程还原，记录方法名、签名和调用时序，不包含实参值。
- 临时 Java 反射已确认类和签名，附加期间曾观察到 App 退出，原因未定。未隐藏工具或更改反调试检查；已卸载会话、移除诊断服务和端口转发。实际调用链由 Android 自带方法追踪取得。

在已观察到的 S 模式下，方法追踪确认以下关系（`b`、`g` 为 `cmbkb.pb.util` 下的类）：

```text
原生输入写入 b.t(int, String)
  → SMCryptKY.CMBSM4EncryptWithECB(byte[], byte[])    [键盘内部状态]

CMBKeyboardOpenService$c.handleMessage(Message)
  ├─ CMBKeyboardOpenService.c0(int)
  │    └─ CMBApplication.getSessionId()             [读取当前 App 会话]
  ├─ b.p(String, int)
  │    ├─ b.a() → SMCryptKY.CMBSM4DecryptWithECB(...) [恢复内部输入]
  │    └─ b.c(String, int, boolean, String)
  │         └─ g.b(byte[])
  │              └─ SMCryptKY.CMBSM2Encrypt(byte[], byte[])
  │                   └─ SecureRandom.nextBytes(byte[])
  └─ CMBKeyboardOpenService.g0(String, int, String)   [组装 JSON 回调]
```

`c0()`、`b.p()` 和回调组装是同一消息处理器里的分支调用；图中没有把 `b.p()` 画成 `c0()` 的子调用。`c0()` 还调用随机数和字符串处理方法。`g0()` 的子调用是创建并填充 `JSONObject`，不是加密入口。`h0()` 未出现在该 S 模式输入样本中，不能凭签名认定它等价于 `g0()`。

**会话结论**：虽然 H5 没传 `encFactor`，原生 S 模式在转换链里实际读取了 App 的 `getSessionId()`。因此不应把输入建模为“只传六位明文就得到可用交易密文”。追踪未采集值，不能确定会话 ID 具体怎样进入待加密数据、`b.c` 四个参数的角色、SM2 公钥选择与轮换，或会话是否跨重新登录有效。SM2 内调用了安全随机数，也不应以两次密文逐字相等作为正确性的判断。

**候选实现**：优先验证同一 App 进程、同一会话内，能否让 `b.c(...)` 或它的上一层复用原有参数组装，而不创建可见键盘。不要把仅做包装的 `g0(...)` 或只做 SM2 运算的 `g.b(...)` 当成完整入口。验证先用虚构密码，拦截全部提交路径，只比较调用链、输出格式及成功状态；若要绕过安全输入组件，按 `AGENT_WORKFLOW.md` §7 先说明具体做法并取得用户确认。未验证前不做开关或接真实交易。

证据：临时目录 `/private/tmp/cmb-native-plan/` 下的 `class-signatures-27405.json`、`keyboard-input-paths.txt` 和 `keyboard-input.trace`。该输入追踪文件 SHA-256 为 `a24be7935e13410999b8e0417bd8f7aed272eda4a893849c6c48a266147fe5d3`。

## 无可见键盘的转换探针

经用户确认，在项目模拟器给招行 App UID 临时加 IPv4 和 IPv6 出站拦截后启动 App。探针使用虚构的六位输入，只在 App 主线程运行原加密组件。探针没有进入购买页或主动登录。测试后移除诊断服务、端口转发、追踪文件和临时网络规则。

最终复核路径：

1. 构造 `CMBKeyboardOpenService`，通过 `KEY_PARAMS` 提供与网页相同形状的请求。`parseAndCheckParams()` 接受 `encType=S`、`needEncrypt=true`、`maxLength=6` 和正数 `elementPointY`，将内部模式设为 `1`。
2. 将解析出的模式传给 `c0(1)`，从当前 App 环境生成上下文。传 `6` 时返回空，不能把密码长度当作该方法的参数。
3. 独立构造 `cmbkb.pb.util.b`，经 `t()` 写入六位虚构数字，再调用 `p()` 转换。ART 方法追踪和计数均观测到 `SMCryptKY.CMBSM2Encrypt` 与底层 `SM2.CMBSM2Encrypt` 各一次。
4. `g0()` 组装 `text`、`length`、`textHash` 三个字段。`length=6`，`text` 是 230 个十六进制字符，与普通购买演练的样本长度相同。原 `callKeyBoard()` 的调用次数为零。

探针使用了 APK 内部方法和混淆字段。此次结果证明该版本可以跳过可见键盘完成转换与回调组装，尚未验证真实购买页采用的登录会话与生成结果是否兼容，也未验证银行是否接受。后续优先在当前购买 WebView 的会话中阻断提交并比较输出结构，同时明确版本匹配和凭据通道，再决定是否接入设置。仅在临时文件记录形状、计数和方法名，未保存会话值、明文或密文。

临时证据：`/private/tmp/cmb-native-plan/headless-traced.json` 和 `/private/tmp/cmb-native-plan/headless-proof.trace`。

## 真实购买页的同会话演练

按用户确认使用 `133045A / 0.01 元`。打开并核对唯一购买表单，先拦截 `doBuy`、`entrustBuy` 和 `entrustOtherCardBuy`，再走原预检查、资料加载和风险文本确认。原生探针拦截本页唯一一次 `callKeyBoard()`，保留已经由银行桥初始化的服务实例。转换前封锁 App 的 IPv4 和 IPv6 出站流量。

在该实例上使用当前会话生成上下文，用独立辅助类转换六位虚构输入，原 `g0()` 组装 `text`、`length`、`textHash`。输出为 230 个十六进制字符，回调长度为 6，转换前后会话相同。两次控件检查均未发现安全键盘，提交尝试数为 0。该次 SM2 钩子计数为 0，算法调用依据上面的离线方法追踪，不将本次计数作为算法证据。结果只验证到购买页同会话的本地转换和回调形状，未把回调交给页面确认或银行验证。

演练结束后关闭 App，并清理临时探针、追踪文件和出站规则。元数据保存在 `/private/tmp/cmb-native-plan/connected-headless-result.json`。

## 单次真实提交

用户明确确认 `133045A / 0.01 元` 的一次真实提交及临时 Frida 凭据通道。受信任脚本在进程内读取交易密码，App 原加密组件完成转换。购买页通过原密码面板确认处理器进入原交易接口。页面保护核对了产品和金额，只放行一次接口调用，并关闭该请求的自动重试。

页面记录确认处理器触发一次、`doBuy` 一次、购买接口一次。原接口返回未受理。用户提供的截图补充了页面提示 `MBJUS04-国密加解密异常。`。这定位到国密处理环节，尚未确定是公钥、待加密数据组装、会话材料还是其他国密校验差异。未重试，未保存真实密码、密文或会话值。

原生追踪显示，普通键盘路径会设置 `setPasswordHelper()` 和 `setCMBKeyboardAPI()`，随后 `b.p()` 读取 `cmbkb.pb.cmbsafe.d.e()` 的状态。本次探针拦截整个 `callKeyBoard()` 并另建辅助类，跳过了这两项初始化。下一轮先用虚构输入在同一进程中比较两条路径的初始化状态、进入 SM2 前的数据结构和公钥来源，仅输出差异标志。上次回调字段和密文长度相同，仍未证明银行可以解密。

## 同会话对照定位公钥选择差异

在 `133045A / 0.01 元` 购买页，通过原键盘输入六位虚构数字作为基线。拦截购买接口及转换阶段的 App 出站流量。用独立辅助类在同一进程内复现旧参数和修正参数，比较 SM2 的两个入参数组，仅输出长度和相等标志。

原处理器用 `CMBKeyboardOpenService.v(service)` 取 `c0()` 的参数，本次为 `1`。另用 `CMBKeyboardOpenService.I(service)` 取 `b.p()` 第二个参数，本次为 `0`。旧无键盘脚本把同一个 `1` 传给了两个方法。

| 路径 | `b.p()` 第二参数 | 与原键盘公钥一致 | 与原键盘待加密数据一致 |
|---|---:|---|---|
| 旧无键盘参数，使用相同虚构输入和同一份上下文 | 1 | 否 | 是 |
| 读取原服务的参数，使用相同虚构输入和同一份上下文 | 0 | 是 | 是 |
| 读取原服务的参数，重新生成上下文 | 0 | 是 | 否，仍为 18 字节且包含同一虚构输入 |

三组均调用原 SM2 并生成 230 字符的输出。相同上下文中，唯一更改 `b.p()` 第二个参数就恢复了原键盘公钥，这确认了旧脚本的公钥选择差异，与银行报国密加解密异常相符。应分别从原服务读取两个参数，避免把 `0` 写成所有模式的固定值。

直接从诊断脚本调用时，钩子漏采了加密入参，ART 追踪仍记录了 SM2 调用。最终用临时 Java 调度器在主线程调用同一个方法，完整采集了对照所需的布尔结果。此轮原键盘已完成初始化，所以比较验证了公钥选择修正，尚未证明完全省略键盘初始化时仍有相同输入。提交尝试为零。

临时比较元数据：`/private/tmp/cmb-native-plan/keyboard-java-comparison-result.json`。

## 修正后的单次真实提交

按用户确认再次用 `133045A / 0.01 元` 验证。捕获真实购买页的原生服务，分别读取 `v(service)` 和 `I(service)`。本次 `c0()` 参数为 `1`，`b.p()` 第二参数为 `0`，并在读取真实凭据前确认会话未变化、键盘组件状态与原基线一致。转换期间拦截 App 出站，复核表单及密码面板后恢复网络，由原确认处理器提交。

`doBuy` 和原购买接口各调用一次。接口返回受理，结果页显示「提交成功」。本次验证覆盖完全不显示安全键盘的实单路径。临时诊断已清理，凭据仅用于此次提交。购买路径仍为临时实验，尚未接入设置。

## 管理 App 接入

「模拟密码输入」默认关闭，适用于 App 单笔购买、演练及新布防。无键盘组件按安装的招行 APK 校验版本，在项目模拟器内临时启动带认证的回环连接。原组件只把转换结果交给购买页。页面复核产品、金额和会话，按演练或真实模式决定是否放行一次确认。正式代码使用 `133045A / 0.01 元` 的虚构输入完成过不提交演练。

## 证据与复查

公开静态入口：

- [购买页](https://mobile.cmbchina.com/IEntrustFinance/subsidiaryfinancing/saentrustbuy.html)
- [购买脚本](https://img2.mb.cmbimg.com/static/ientrustfinance/subsidiaryfinancing/js/saentrustbuy.5b669afa.min.js)
- [密码组件](https://img2.mb.cmbimg.com/static/ientrustfinance/subsidiaryfinancing/js/chunk-ui.ebc92261.min.js)
- [框架脚本](https://img2.mb.cmbimg.com/static/ientrustfinance/subsidiaryfinancing/js/chunk-frame.cf0a63c2.min.js)

当日下载的 UI / frame 与项目既有临时静态副本逐字节一致：

| 文件 | SHA-256 |
|---|---|
| chunk-ui | `1750bf41b9a7291b76bc31e5460ce14690fadd1bb05a75798398e0e17c74af01` |
| chunk-frame | `6aad9e8b87c917c82066de4757d6738397d250043971bc934da24add41e6eb2b` |
| 安装 APK | `83959ebc9a9cad18d52206bf3383544a271d84b690971ef35bb8de7799e9763e` |

REA 对购买脚本、UI、frame 三个选定文件完成静态分析，完整 Evidence：`ev_04afa17a80622f49956f086ea6ce240f66622f44bee48f2c942bf2c07a481939`，临时导出为 `/private/tmp/cmb-password-rea-bundle.json`；这不是运行时验证。上述具体赋值和方法体结论同时来自对原脚本的直接检查，APK 结果来自普通 ZIP/DEX 解析，不是 REA Android 反编译结果。临时文件可能被系统清理，长期复查应以上述版本和哈希重新取得静态文件。
