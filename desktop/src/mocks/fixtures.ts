import type { Device, Favorite, HistoryRecord, Status, SystemInfo, Task } from '../api/types'
import { localISO } from '../lib/utils'

/**
 * Mock scenarios, picked with `?scenario=` in the page URL (before the `#`):
 * idle (default), armed, redemption, firing, empty, error.
 */
export type Scenario = 'idle' | 'armed' | 'redemption' | 'firing' | 'empty' | 'error'

export function scenario(): Scenario {
  const value = new URLSearchParams(location.search).get('scenario')
  return (
    (['idle', 'armed', 'redemption', 'firing', 'empty', 'error'] as const).find((s) => s === value) ?? 'idle'
  )
}

const inMinutes = (minutes: number) => localISO(new Date(Date.now() + minutes * 60_000))

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

export function makeStatus(task: Task | null, favorites: Favorite[], logs: string[]): Status {
  const live = task?.phase && ['armed', 'preparing', 'waiting', 'firing'].includes(task.phase)
  return {
    task,
    running: Boolean(live),
    last_tick_age_s: live ? 4 : 5745,
    logs: logs.slice(-40),
    agent: live ? { state: 'watching', session: 'mock', last_seen: localISO(new Date()) } : { state: 'none' },
    credentials: { state: 'configured' },
    mail_configured: true,
    log_path: '/mock/var/night/watch.log',
    favorites,
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

export const SETTINGS = {
  reopen_deadline: 3,
  drill_form_deadline: 3,
  cold_start_minutes: 7,
  first_offset_ms: 200,
  first_max_retries: 5,
  irregular_advance_ms: 200,
  irregular_window_minutes: 5,
  irregular_retry_min_ms: 50,
  irregular_retry_max_ms: 250,
}
