# 收藏（产品代码 + 标题 + 测试项）

状态：**已实现**（2026-11-04；2026-11-05 增加测试项）。入口在侧边栏「收藏」；布防与单笔购买演练的代码框下方有收藏快捷选择。**2026-11-08 v2** 新增额度时间（首发 / 捡漏 / 常规）和收藏页「设置」弹窗（测试项设置并入其中），细节见 `README.md`「管理 App → 页面 → 收藏」和 `AGENT_WORKFLOW.md` §1；本文其余内容保留为 v1 方案历史。

## 要做什么

- 侧边栏在「历史」上面新增一个「收藏」页。
- 收藏项 = 产品代码 + 标题，可以添加、改标题、删除。
- **任何可以填产品代码的地方都能从收藏里选**。当前有三处：任务页的布防表单、演练页的「单笔购买演练」、「计划」页布防列表的每一行（2026-11-06 起）。
- 后续功能点：标题以后自动从招行获取；现在由账户持有人手动填写。

## 测试项（2026-11-05）

- 可以把**一项**收藏设为测试项，并给一个测试金额（大于 0、最多两位小数，无上限）。同时只能有一项。
- 演练布防、单笔购买演练打开时自动带入这个产品和金额；已经输入的内容优先，不会覆盖。
- 读取入口：`admin_cli.py status` 的 `test_item`（`{code, amount, title}` 或 `null`）、`admin_cli.py favorites --test`。后续测试脚本可直接读这两处。
- 测试项只是**默认参数**，不构成付款授权：真实付款仍要在确认页勾选大字号金额，并遵守“一笔只提交一次”。
- 改标题不会清掉测试项；删除该收藏会一并清掉；2026-11-08 v2 起改为在设置弹窗取消勾选「设为测试项」并保存，即只清测试项。

## 实现

- 数据放 `var/favorites.json`（Git 忽略，0600），Python 维护：

  ```json
  [{"code": "JX040229", "title": "招睿丰和 30 天", "test_amount": "0.01"}]
  ```

  代码 4–20 位字母数字（和 `night_watch` 的校验一致），标题 1–40 字，按代码忽略大小写去重；`test_amount` 最多出现在一项。
- `src/favorites.py`：`add` / `remove` / `set_test` / `clear_test` / `test_item`；保留旧文件的未知字段忽略行为。
- `admin_cli.py`：`favorites --list / --add CODE --title TITLE / --remove CODE / --set-test CODE --test-amount AMOUNT / --clear-test / --test`；`status` 同时带 `favorites` 和 `test_item`。
- HTTP：`POST /api/favorites/test {code, amount}`、`DELETE /api/favorites/test`；旧的增删改接口不变。
- **2026-11-08 v2**：数据增加 `quota_times`（`issue` / `bargain` / `regular`；首发 `date` + `time`，周重复 `weekdays` + `time`；`amount_wan` 以万为单位、省略表示「不定额度」；`note`；单条收藏 ≤50 条），由 `save_item` 保存；CLI 增加 `favorites --save`（stdin JSON），HTTP 增加 `PUT /api/favorites/{code}`（管理 App 设置弹窗保存走它）；`test_amount` 和上面旧接口的语义不变。同日又加 `recent_annualized`（近期年化，参考值，规范化为 `N.NN%`，可空）和额度时间与标题输入框左对齐。细节见 `README.md` 和 `AGENT_WORKFLOW.md` §1。
- App：2026-11-08 v2 起，每行用「设置」按钮打开设置弹窗，测试项（Checkbox + 金额）和额度时间都在弹窗里配置，保存走 `PUT /api/favorites/{code}`；保存后代码下方显示「测试 ¥…」Tag。布防（仅演练）和单笔购买演练打开时自动填入测试项；收藏快捷选择里的测试项带 Tag 并排在最前，点它同时填入产品和金额。计划页每个布防项也有收藏快捷选择，点测试项会同时填入产品代码和测试金额；计划项不做自动带入（一份计划有多项）。

## 历史成功提交次数 Tag（2026-11-09）

- 收藏页每行产品代码下方显示绿色「N 单」Tag：N 是该产品代码在历史记录里成功提交的订单数。
- 统计在前端 `desktop/src/lib/history.ts` 的 `successCountByCode()`，复用历史页同一套结果分类：演练、失败、已取消、结果未知不计入，同一代码忽略大小写；没有成功记录时不显示。
- 只读现有 `GET /api/history`；后端、CLI 与 `var/favorites.json` 均无改动。

## 不做

- 收藏不存交易凭据或授权信息；只存测试金额和额度时间，且都不当作付款授权。
