import type { Mode, Plan, PlanItem, PlanStatus } from '../api/types'
import { formatAmount, parseLocal, type Tone } from './utils'

/** Same cap as src/watch_plan.py MAX_ITEMS. */
export const PLAN_MAX_ITEMS = 20

const ITEM_STATE_NAMES: Record<string, string> = {
  pending: '待执行',
  running: '执行中',
  done: '已完成',
  failed: '失败',
  skipped: '跳过',
}

export function itemStateName(state: string | null | undefined) {
  if (!state) return '待执行'
  return ITEM_STATE_NAMES[state] ?? state
}

/** Badge tone for one plan item: live accent, done good, failed warn. */
export function itemStateTone(state: string | null | undefined): Tone {
  if (state === 'running') return 'accent'
  if (state === 'done') return 'good'
  if (state === 'failed') return 'warn'
  return 'muted'
}

const PHASE_NAMES: Record<string, string> = {
  idle: '待开始',
  running: '运行中',
  done: '已完成',
  aborted: '已中止',
  disarmed: '已取消',
}

/** `null` means there is no saved plan at all. */
export function planPhaseName(phase: string | null | undefined) {
  if (!phase) return '未计划'
  return PHASE_NAMES[phase] ?? phase
}

export function planPhaseTone(phase: string | null | undefined): Tone {
  if (phase === 'running') return 'accent'
  if (phase === 'done') return 'good'
  if (phase === 'aborted') return 'warn'
  if (phase === 'idle') return 'blue'
  return 'muted'
}

const PRIMARY_NAMES: Record<string, string> = {
  pending: '待开始',
  running: '运行中',
  done: '已完成',
  failed: '失败',
  skipped: '已跳过',
  cancelled: '已取消',
  expired: '已过期',
  unknown: '未知',
}

const PRIMARY_TONES: Record<string, Tone> = {
  pending: 'blue',
  running: 'accent',
  done: 'good',
  failed: 'warn',
  skipped: 'muted',
  cancelled: 'muted',
  expired: 'warn',
  unknown: 'warn',
}

const SECONDARY_NAMES: Record<string, string> = {
  scheduled: '已排程',
  immediate: '立即准备',
  partially_expired: '部分过期',
  time_passed: '时间已过',
  preparing: '准备中',
  waiting: '等待查询',
  submitting: '提交中',
  starting: '准备中',
  heartbeat_timeout: '心跳超时',
  process_exited: '进程已退出',
  success: '成功',
  dry_run: '演练完成',
  completed: '已完成',
  result_unknown: '结果未知',
  config_changed: '配置已变',
  timeout: '超时',
  no_quota: '无额度',
  purchase_failed: '购买失败',
  manual_cancel: '手动取消',
  skipped: '已跳过',
  aborted: '已中止',
}

/** Primary status text; also used for the plan-level badge. */
export function statusPrimaryName(status: PlanStatus | null | undefined) {
  return status ? (PRIMARY_NAMES[status.primary] ?? status.primary) : '未计划'
}

/** Primary status determines the badge color. */
export function statusPrimaryTone(status: PlanStatus | null | undefined): Tone {
  return status ? (PRIMARY_TONES[status.primary] ?? 'muted') : 'muted'
}

export function statusSecondaryName(status: PlanStatus | null | undefined) {
  return status?.secondary ? (SECONDARY_NAMES[status.secondary] ?? status.secondary) : null
}

/** Fallback for mock/legacy responses that predate the explicit status object. */
export function itemStatus(item: PlanItem | null | undefined, now: Date = new Date()): PlanStatus | null {
  if (!item) return null
  if (item.status) return item.status
  const state = item.state ?? 'pending'
  if (state === 'done') {
    const outcome = item.outcome
    return {
      primary: 'done',
      secondary: outcome === 'dry_run' ? 'dry_run' : outcome === 'success' ? 'success' : 'completed',
      description: item.result,
    }
  }
  if (state === 'running') return { primary: 'running', secondary: 'starting' }
  if (state === 'failed') {
    return {
      primary: 'failed',
      secondary: item.outcome === 'unknown' ? 'result_unknown' : 'purchase_failed',
      description: item.result,
    }
  }
  if (state === 'skipped') {
    return { primary: 'skipped', secondary: 'skipped', description: item.result }
  }
  const at = parseLocal(item.at)
  if (at && at.getTime() <= now.getTime()) {
    return {
      primary: 'expired',
      secondary: 'time_passed',
      description: '计划时间已过，未在应用运行期间执行',
    }
  }
  return { primary: 'pending', secondary: item.prep_mode === 'immediate' ? 'immediate' : 'scheduled' }
}

/** Fallback plan status when the backend has not supplied one. */
export function planStatus(plan: Plan | null | undefined, now: Date = new Date()): PlanStatus | null {
  if (!plan) return null
  if (plan.status) return plan.status
  const phase = plan.phase ?? 'idle'
  if (phase === 'running') return { primary: 'running', secondary: 'waiting' }
  if (phase === 'done') return { primary: 'done', secondary: 'completed', description: plan.result }
  if (phase === 'aborted') return { primary: 'failed', secondary: 'aborted', description: plan.result }
  if (phase === 'disarmed')
    return { primary: 'cancelled', secondary: 'manual_cancel', description: plan.result }
  const items = plan.items ?? []
  const expired = items.filter((item) => itemStatus(item, now)?.primary === 'expired').length
  if (items.length && expired === items.length) {
    return {
      primary: 'expired',
      secondary: 'time_passed',
      description: '计划时间已过，未在应用运行期间执行',
    }
  }
  if (expired)
    return { primary: 'pending', secondary: 'partially_expired', description: `有 ${expired} 项已过期` }
  return { primary: 'pending', secondary: 'scheduled' }
}

/** The item the plan is on: the running one, else the first still pending. */
export function nextItem(plan: Plan | null | undefined): PlanItem | null {
  const items = plan?.items ?? []
  return (
    items.find((item) => item.state === 'running') ?? items.find((item) => item.state === 'pending') ?? null
  )
}

const pad = (value: number) => String(value).padStart(2, '0')

/** Short human countdown: "42 秒后", "07:32 后", "03:05 后", "1 天 01:30 后". */
export function countdownText(targetISO: string | null | undefined, now: Date = new Date()) {
  const target = parseLocal(targetISO)
  if (!target) return '—'
  const seconds = Math.floor((target.getTime() - now.getTime()) / 1000)
  if (seconds <= 0) return '已到时间'
  if (seconds < 60) return `${seconds} 秒后`
  if (seconds < 3600) return `${pad(Math.floor(seconds / 60))}:${pad(seconds % 60)} 后`
  if (seconds < 86_400)
    return `${pad(Math.floor(seconds / 3600))}:${pad(Math.floor((seconds % 3600) / 60))} 后`
  const days = Math.floor(seconds / 86_400)
  const hours = Math.floor((seconds % 86_400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return `${days} 天 ${pad(hours)}:${pad(minutes)} 后`
}

/** Exact cents so the confirm screen never shows a float artefact. */
function amountCents(text: string) {
  const match = /^(\d+)(?:\.(\d{1,2}))?$/.exec(text.trim().replace(/,/g, ''))
  if (!match) return 0
  return Number(match[1]) * 100 + Number(`${match[2] ?? ''}00`.slice(0, 2))
}

function formatCents(cents: number) {
  return formatAmount(`${Math.floor(cents / 100)}.${pad(cents % 100)}`)
}

/** How many defenses and how much money the whole plan covers. */
export function planTotals(plan: Plan | null | undefined): { count: number; amount: string } {
  const items = plan?.items ?? []
  const cents = items.reduce((sum, item) => sum + amountCents(item.amount ?? ''), 0)
  return { count: items.length, amount: formatCents(cents) }
}

/** "HH:MM" of a backend ISO time, or "—". */
export function isoClock(value: string | null | undefined) {
  const text = (value ?? '').trim().replace(' ', 'T')
  const match = /T(\d{2}:\d{2})/.exec(text)
  return match ? match[1] : '—'
}

/** <input type="datetime-local"> value → backend ISO seconds; "" when invalid. */
export function itemInputToISO(value: string) {
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})(?::(\d{2}))?$/.exec(value.trim())
  if (!match) return ''
  return `${match[1]}:${match[2] ?? '00'}`
}

/** Backend ISO (with seconds/microseconds) → <input type="datetime-local"> value. */
export function isoToItemInput(value: string | null | undefined) {
  const text = (value ?? '').trim().replace(' ', 'T')
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})/.exec(text)
  return match ? match[1] : ''
}

/** One editable row in the plan list. */
export interface PlanDraftItem {
  /** Stable React key; never sent to the backend. */
  key: string
  code: string
  amount: string
  /** <input type="datetime-local"> value, e.g. "2026-11-07T09:00". */
  at: string
  mode: Mode
  /** The saved item behind this row; cleared as soon as the row is edited. */
  saved?: PlanItem | null
}

let draftSequence = 0

/** A blank row for 「添加布防」. */
export function emptyDraftItem(mode: Mode = 'first_launch'): PlanDraftItem {
  draftSequence += 1
  return { key: `draft-${draftSequence}`, code: '', amount: '', at: '', mode }
}

/** Seeds the editor from the saved plan, keeping the backend's order. */
export function draftFromPlan(plan: Plan | null | undefined): PlanDraftItem[] {
  return (plan?.items ?? []).map((item, index) => ({
    key: item.item_id ?? `saved-${index}`,
    code: item.code ?? '',
    amount: item.amount ?? '',
    at: isoToItemInput(item.at),
    mode: item.mode === 'redemption' ? 'redemption' : 'first_launch',
    saved: item,
  }))
}

/** First local format issue in one row; backend `problems` stay authoritative. */
export function draftItemProblem(item: PlanDraftItem): string | null {
  const code = item.code.trim()
  if (!code) return '请填写产品代码。'
  if (!/^[A-Za-z0-9]{4,20}$/.test(code)) return '产品代码须为 4–20 位字母或数字。'
  const amount = item.amount.trim()
  if (!/^[0-9]+(\.[0-9]{1,2})?$/.test(amount) || !(Number(amount) > 0))
    return '金额须为大于 0 的数字，最多两位小数。'
  if (!itemInputToISO(item.at)) return '请选择购买时间。'
  return null
}

export function draftProblems(items: PlanDraftItem[]): string[] {
  return items
    .map((item, index) => {
      const issue = draftItemProblem(item)
      return issue ? `第 ${index + 1} 项：${issue}` : null
    })
    .filter((issue): issue is string => issue !== null)
}

/** What the editor contains; used to tell saved plans from unsaved edits. */
export function draftSignature(items: PlanDraftItem[], dryRun: boolean) {
  return JSON.stringify({
    dry_run: dryRun,
    items: items.map((item) => [item.code.trim(), item.amount.trim(), item.at, item.mode]),
  })
}

/** True when the editor differs from the saved plan (or has never been saved). */
export function planDirty(items: PlanDraftItem[], dryRun: boolean, plan: Plan | null | undefined): boolean {
  return draftSignature(items, dryRun) !== draftSignature(draftFromPlan(plan), plan?.dry_run ?? false)
}
