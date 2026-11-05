/**
 * Purchase chain progress read from watch.log (docs/purchase-chain.md, P1–P12).
 *
 * The watcher writes nothing extra for this: every step already has a fixed
 * log line, so the page infers where the run is from the log it shows anyway.
 * Steps are listed in the order they actually run (P4 runs after P6).
 */

export type StepState = 'done' | 'active' | 'pending' | 'failed' | 'skipped'

export interface Step {
  id: string
  name: string
  /** Real call chain, shown like code. */
  chain: string
  /** Steps from here on run after fired_at; nothing before them can submit. */
  fired?: boolean
}

export const STEPS: Step[] = [
  { id: 'P1', name: '布防', chain: '_arm → query_gate.schedule → spawn_watch' },
  { id: 'P2', name: '夜间巡检', chain: 'run → ensure_emulator · ensure_awake · health_network' },
  { id: 'P3', name: '冷启动登录', chain: 'prepare → login_fresh → cold_start → secure_input.login' },
  { id: 'P5', name: '打开过渡容器', chain: 'gated_fire → query_gate.run → watch → blank_target' },
  { id: 'P6', name: '进入购买页并挂起', chain: 'Page.navigate → query_gate.js install() → 挂起 queryBuy' },
  { id: 'P4', name: '预读凭据与预热', chain: 'prepared() → load_payment_password → warm' },
  { id: 'P7', name: '到点查询与重试', chain: '包装 queryBuy → waitUntil → 原 queryBuy → retryRange' },
  { id: 'P8', name: '发现有额度', chain: 'watch ← __cmbGateReady → READ_STATE → fu.dump' },
  { id: 'P9', name: '提交前复核', chain: 'fast_buy_uia2.run → verify_prepared → 额度校验 → before_submit' },
  {
    id: 'P10',
    name: '风险确认',
    chain: 'risk_confirm.run → preAmountExam → QuickInput → Confirm → callPwd',
    fired: true,
  },
  {
    id: 'P11',
    name: '输入交易密码',
    chain: 'wait_for → enter_password → wait_keypad_stable → send_commands',
    fired: true,
  },
  { id: 'P12', name: '读结果', chain: 'wait_result → log_timings → query_gate.finish', fired: true },
]

/** A log line that proves the run has reached step index `reach` (all before it done). */
const MILESTONES: [RegExp, number][] = [
  [/值守已开始|不定时抢购已开始/, 1],
  [/开始准备：冷启动并登录|立即冷启动并登录/, 2],
  [/登录成功|已登录/, 3],
  [/uia2 已连接并预热/, 5],
  [/购买页已就绪，queryBuy 已挂起/, 6],
  [/queryBuy 第 \d+ 次：有额度/, 7],
  [/queryBuy 有额度，表单已就绪/, 8],
  [/进入单次购买流程/, 9],
  [/JS 风险确认完成/, 10],
  [/已提交一次|演练：密码已输入/, 11],
  [/结果页提示：|未能确认结果|演练：输完密码/, 12],
]
const START = /通知：(值守已开始|不定时抢购已开始)/
const STOPPED = /值守中止|值守停止，未提交|未提交：|结果需要人工确认|窗口内没有买到/
const QUERY = /queryBuy 第 (\d+) 次：(\S+?)，往返 (\d+) ms/
const STAMP = /^\d{2}-\d{2} (\d{2}:\d{2}:\d{2})/
/** "耗时（毫秒，从有额度起）：表单复核 +60，风险确认 +711，…" */
const TIMING = /耗时（毫秒，从有额度起）：(.+)$/
const TIMING_STEP: Record<string, string> = {
  表单复核: 'P9',
  等手续费查询: 'P10',
  风险确认: 'P10',
  密码页: 'P11',
  '输完密码（演练，未点确定）': 'P11',
  提交: 'P11',
  结果页: 'P12',
}

export interface Query {
  attempt: number
  outcome: string
  ms: number
}

export interface Progress {
  states: StepState[]
  /** Index of the step running now, or -1 when finished or not started. */
  active: number
  /** Clock time (HH:MM:SS) a step finished, from the log line that proved it. */
  finishedAt: Record<string, string>
  /** Milliseconds after quota for P9–P12, from the watcher's timing line. */
  offsets: Record<string, number>
  queries: Query[]
  dryRun: boolean
}

/** Phase fallback when the log window no longer reaches back to the task start. */
const PHASE_REACH: Record<string, number> = { armed: 1, preparing: 2, waiting: 6, firing: 9 }

export function readProgress(lines: string[], phase: string, dryRun = false): Progress {
  let start = -1
  for (let i = lines.length - 1; i >= 0; i--) {
    if (START.test(lines[i])) {
      start = i
      break
    }
  }
  const own = start >= 0 ? lines.slice(start) : []
  let reach = start >= 0 ? 1 : (PHASE_REACH[phase] ?? 0)
  let stopped = false
  const finishedAt: Record<string, string> = {}
  const offsets: Record<string, number> = {}
  const queries: Query[] = []
  let lastStamp = ''
  if (start >= 0) finishedAt.P1 = own[0].match(STAMP)?.[1] ?? ''

  for (const line of own) {
    lastStamp = line.match(STAMP)?.[1] ?? lastStamp
    for (const [pattern, index] of MILESTONES) {
      if (pattern.test(line) && index > reach) {
        for (let i = reach; i < index; i++) finishedAt[STEPS[i].id] ??= lastStamp
        reach = index
      }
    }
    const query = line.match(QUERY)
    if (query) queries.push({ attempt: Number(query[1]), outcome: query[2], ms: Number(query[3]) })
    const timing = line.match(TIMING)
    if (timing) {
      // Labels may hold a comma inside their brackets: 输完密码（演练，未点确定）.
      for (const [, label, value] of timing[1].matchAll(/((?:[^，\s（]|（[^）]*）)+) \+(\d+)/g)) {
        const id = TIMING_STEP[label]
        // P11 has two marks (panel shown, password typed/submitted): keep the later.
        if (id) offsets[id] = Math.max(offsets[id] ?? 0, Number(value))
      }
    }
    if (STOPPED.test(line)) stopped = true
  }

  // A drill stops once the password is typed: P12 never runs.
  const last = STEPS.length - 1
  const finished = reach >= (dryRun ? last : STEPS.length)
  const states: StepState[] = STEPS.map((_, i) => {
    if (dryRun && i === last) return finished ? 'skipped' : 'pending'
    if (i < reach) return 'done'
    if (i === reach && !finished) return stopped ? 'failed' : 'active'
    return 'pending'
  })
  return {
    states,
    active: finished || stopped ? -1 : reach,
    finishedAt,
    offsets,
    queries,
    dryRun,
  }
}
