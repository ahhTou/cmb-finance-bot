import type {
  Device,
  Favorite,
  HistoryRecord,
  Mode,
  Plan,
  PlanItem,
  PushConfig,
  Status,
  SystemInfo,
  Task,
} from '../api/types'
import { localISO } from '../lib/utils'

/**
 * Mock scenarios, picked with `?scenario=` in the page URL (before the `#`):
 * idle (default), armed, redemption, firing, progress, empty, error, plan.
 * `progress` replays the real 11-05 11:06 drill log step by step.
 * `plan` presets one idle two-item plan for the plan page demo and screenshots.
 */
export type Scenario =
  | 'idle'
  | 'armed'
  | 'redemption'
  | 'firing'
  | 'progress'
  | 'empty'
  | 'error'
  | 'plan'
  | 'plan-done'

export function scenario(): Scenario {
  const value = new URLSearchParams(location.search).get('scenario')
  return (
    (
      ['idle', 'armed', 'redemption', 'firing', 'progress', 'empty', 'error', 'plan', 'plan-done'] as const
    ).find((s) => s === value) ?? 'idle'
  )
}

const inMinutes = (minutes: number) => localISO(new Date(Date.now() + minutes * 60_000))

const stamp = () => localISO(new Date()).slice(5).replace('T', ' ')

/**
 * The 11-05 11:06 drill (133045A, 0.01) as [log line, phase after it, pause ms].
 * Lines without a time stamp are prints from the purchase script, as in watch.log.
 */
export const DRILL_SCRIPT: [() => string, string, number][] = [
  [() => `${stamp()} 通知：值守已开始：133045A 0.01 元（演练）`, 'armed', 1500],
  [() => `${stamp()} 开始准备：冷启动并登录`, 'preparing', 2200],
  [() => `${stamp()} 输入图案（第 1/3 次）`, 'preparing', 1200],
  [() => '已发送登录手势（约 5.3 秒）；请在模拟器确认登录结果。', 'preparing', 1600],
  [() => `${stamp()} 通知：登录成功（第 1 次图案）`, 'preparing', 1800],
  [() => 'uia2 已连接并预热 0.06s', 'preparing', 1200],
  [() => `${stamp()} 通知：购买页已就绪，queryBuy 已挂起`, 'waiting', 2000],
  ...[1, 2, 3, 4, 5].map((n): [() => string, string, number] => [
    () => `${stamp()} queryBuy 第 ${n} 次：售罄，往返 ${170 + ((n * 37) % 60)} ms`,
    'waiting',
    700,
  ]),
  [() => `${stamp()} queryBuy 第 6 次：有额度，往返 305 ms`, 'waiting', 600],
  [() => `${stamp()} queryBuy 有额度，表单已就绪`, 'firing', 700],
  [() => '购买页显示单笔可购买额度 50000000 元（本次 0.01 元）', 'firing', 900],
  [() => 'JS 风险确认完成：原预检查、资料加载及文本校验通过，密码面板已请求。', 'firing', 1100],
  [() => '交易密码输入：第 1/2 轮', 'firing', 600],
  [() => '演练：密码已输入，确定可点；未点确定。', 'firing', 500],
  [() => '演练：输完密码约 1.85 秒；未点确定、未提交，已关闭密码框。', 'firing', 300],
  [
    () =>
      `${stamp()} 耗时（毫秒，从有额度起）：表单复核 +60，风险确认 +711，密码页 +1101，输完密码（演练，未点确定） +1853`,
    'firing',
    6000,
  ],
]

export const LOG_LINES = [
  ...Array.from(
    { length: 40 },
    (_, i) =>
      `11-04 18:${String(10 + Math.floor(i / 4)).padStart(2, '0')}:${String((i * 13) % 60).padStart(2, '0')} 心跳：模拟器在线，购买页等待中（第 ${i + 1} 次）`,
  ),
  '11-04 18:30:01 冷启动模拟器，等待开机完成',
  '11-04 18:30:24 招行 App 已启动，进入登录页',
  '11-04 18:30:31 九宫格图案输入：第 1/3 次',
  '11-04 18:30:33 登录成功，进入理财首页',
  '11-04 18:30:40 打开产品 JX040229 购买页，等待开售',
  '11-04 18:31:02 查询门控已挂起 queryBuy，按配置轮询',
]

export const FAVORITES: Favorite[] = [
  { code: 'JX040229', title: '招睿丰和 30 天' },
  { code: '133045A', title: '日日金 1 号' },
  { code: 'GS110021', title: '季季宝' },
]

/** Fake push config for demos; never the account holder's real server or topic. */
export function makePush(kind: Scenario): PushConfig {
  if (kind === 'empty') return { configured: false, server: null, topic: null, token_set: false }
  return {
    configured: true,
    server: 'https://ntfy.example.com/',
    topic: 'cmb-demo',
    token_set: true,
  }
}

export function makeTask(kind: Scenario): Task | null {
  if (kind === 'armed')
    return {
      code: 'JX040229',
      amount: '5000',
      at: inMinutes(4).slice(0, 16).concat(':00'),
      fire_at: inMinutes(4),
      mode: 'first_launch',
      phase: 'waiting',
      prep_minutes: 7,
      patterns_sent: 1,
      armed_at: inMinutes(-3),
      dry_run: true,
    }
  if (kind === 'redemption')
    return {
      code: '133045A',
      amount: '20000',
      at: inMinutes(-1),
      fire_at: inMinutes(-1),
      end_at: inMinutes(4),
      mode: 'redemption',
      phase: 'waiting',
      prep_minutes: 7,
      window_minutes: 5,
      patterns_sent: 1,
      armed_at: inMinutes(-10),
    }
  if (kind === 'firing') return { ...makeTask('armed'), phase: 'firing' }
  if (kind === 'progress')
    return { ...makeTask('armed'), code: '133045A', amount: '0.01', fire_at: inMinutes(0.5), phase: 'armed' }
  if (kind === 'idle')
    return {
      code: '133045A',
      amount: '0.01',
      at: '2026-11-05T09:00:00',
      mode: 'first_launch',
      phase: 'disarmed',
      prep_minutes: 7,
      armed_at: '2026-11-04T19:54:15',
    }
  return null
}

function planItem(item_id: string, code: string, amount: string, minutes: number, mode: Mode): PlanItem {
  return {
    item_id,
    code,
    amount,
    at: inMinutes(minutes),
    mode,
    state: 'pending',
    task_id: null,
    result: null,
    armed_at: null,
    ended_at: null,
  }
}

/** The `plan` scenario: an idle, drill-mode two-item plan with times in the future. */
export function makePlan(kind: Scenario): Plan | null {
  if (kind === 'plan-done') {
    const started = inMinutes(-180)
    const ended = inMinutes(-60)
    return {
      version: 1,
      plan_id: 'mock-plan-done',
      generation: 'mock-gen-done',
      created_at: inMinutes(-240),
      started_at: started,
      ended_at: ended,
      dry_run: true,
      phase: 'done',
      pid: null,
      last_tick: ended,
      settings_revision: 'mock-revision',
      settings_snapshot: SETTINGS,
      result: '完成 1 项，失败 1 项，跳过 0 项',
      items: [
        {
          item_id: 'mock-done-1',
          code: 'JX040229',
          amount: '5000',
          at: inMinutes(-160),
          mode: 'first_launch',
          state: 'done',
          outcome: 'success',
          task_id: 'mock-task-1',
          result: '交易委托已接受',
          armed_at: inMinutes(-167),
          ended_at: inMinutes(-155),
          prep_minutes: 7,
        },
        {
          item_id: 'mock-done-2',
          code: '133045A',
          amount: '20000',
          at: inMinutes(-90),
          mode: 'redemption',
          state: 'failed',
          outcome: 'failed',
          task_id: 'mock-task-2',
          result: '窗口内没有买到',
          armed_at: inMinutes(-97),
          ended_at: inMinutes(-88),
          prep_minutes: 0,
        },
      ],
    }
  }
  if (kind !== 'plan') return null
  return {
    version: 1,
    plan_id: 'mock-plan-0001',
    generation: null,
    created_at: localISO(new Date()),
    started_at: null,
    ended_at: null,
    dry_run: true,
    phase: 'idle',
    pid: null,
    last_tick: null,
    settings_revision: 'mock-revision',
    result: null,
    items: [
      planItem('mock-item-1', 'JX040229', '5000', 40, 'first_launch'),
      planItem('mock-item-2', '133045A', '20000', 130, 'redemption'),
    ],
  }
}

export function makeStatus(task: Task | null, favorites: Favorite[], logs: string[]): Status {
  const live = task?.phase && ['armed', 'preparing', 'waiting', 'firing'].includes(task.phase)
  const test = favorites.find((row) => Boolean(row.test_amount))
  return {
    task,
    running: Boolean(live),
    last_tick_age_s: live ? 4 : 5745,
    logs: logs.slice(-40),
    agent: live ? { state: 'watching', session: 'mock', last_seen: localISO(new Date()) } : { state: 'none' },
    credentials: { state: 'configured' },
    push_configured: true,
    log_path: '/mock/var/night/watch.log',
    favorites,
    test_item: test?.test_amount ? { code: test.code, amount: test.test_amount, title: test.title } : null,
  }
}

export const DEVICE: Device = {
  emulator: { running: true },
  booted: true,
  app_pid: '4127',
  resolution: 'Physical size: 320x640',
  resolution_ok: true,
  awake: true,
  ac_powered: true,
  stay_on: '15',
  screen_timeout: '2147483647',
  lock_disabled: 'true',
}

export const SYSTEM: SystemInfo = {
  on_ac: true,
  clamshell: '"AppleClamshellState" = No',
  watch_caffeinate: true,
  network_ok: true,
  network_s: 0.087,
  sleep_settings:
    'System-wide power settings:\n SleepDisabled\t\t0\nCurrently in use:\n sleep                0\n displaysleep         10\n disksleep            10',
}

export const HISTORY: HistoryRecord[] = [
  {
    code: '133045A',
    amount: '0.01',
    at: '2026-11-04T09:00:00',
    mode: 'first_launch',
    phase: 'done',
    armed_at: '2026-11-04T08:51:02',
    ended_at: '2026-11-04T09:00:03',
    fired_at: '2026-11-04T09:00:01',
    result: '已提交一次，核心流程约 2.04 秒',
  },
  {
    code: 'JX040229',
    amount: '5000',
    at: '2026-11-03T10:15:00',
    mode: 'redemption',
    window_minutes: 5,
    phase: 'aborted',
    armed_at: '2026-11-03T10:05:44',
    ended_at: '2026-11-03T10:20:00',
    result: '窗口内无额度',
    resumes: [{ at: '2026-11-03T10:09:12', by: 'agent:mock', reason: '模拟器重启后恢复' }],
  },
  {
    code: 'GS110021',
    amount: '0.01',
    at: '2026-11-02T09:00:00',
    mode: 'first_launch',
    phase: 'disarmed',
    dry_run: true,
    armed_at: '2026-11-02T08:50:00',
    ended_at: '2026-11-02T08:55:10',
  },
]

export const PLAN_SETTINGS = {
  arm_gap_minutes: 2,
  first_end_slack_minutes: 2,
  end_timeout_minutes: 5,
  grace_seconds: 15,
  poll_seconds: 2,
  heartbeat_seconds: 10,
  kill_wait_seconds: 10,
  heartbeat_timeout_seconds: 60,
}

export const SETTINGS = {
  reopen_deadline: 3,
  drill_form_deadline: 3,
  cold_start_minutes: 7,
  first_offset_ms: 200,
  first_max_retries: 5,
  irregular_advance_ms: 200,
  irregular_window_minutes: 2,
  irregular_retry_min_ms: 300,
  irregular_retry_max_ms: 500,
  irregular_burst_seconds: 60,
  irregular_ramp_seconds: 65,
  irregular_slow_min_ms: 1000,
  irregular_slow_max_ms: 2000,
  irregular_idle_after_seconds: 90,
  irregular_idle_min_ms: 2500,
  irregular_idle_max_ms: 4000,
  password_page_timeout_s: 10,
  keypad_timeout_ms: 1200,
  keypad_stable_ms: 60,
  keypad_stable_samples: 2,
  keypad_sample_gap_ms: 0,
  password_same_digit_gap_ms: 50,
  password_different_digit_gap_ms: 10,
  password_confirm_gap_ms: 150,
  password_confirm_timeout_ms: 600,
  password_retry_gap_ms: 100,
  password_done_gap_ms: 150,
  password_close_wait_ms: 500,
  result_first_wait_ms: 1000,
  result_timeout_s: 20,
}
