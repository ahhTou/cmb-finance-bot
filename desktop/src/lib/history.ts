import type { HistoryRecord } from '../api/types'
import { formatAmount, parseLocal, str, type Tone } from './utils'

/** How many recent real deployments the first screen shows (successes and failures together). */
export const RECENT_LIMIT = 8

/**
 * Metric cards on the complete-history screen are also the list's type filter.
 * They partition the records by result (成功 / 失败 / 已取消 / 演练), the same
 * classification the overview columns use, so a card's number always equals the
 * number of rows its filter shows.
 */
export type HistoryFilter = 'all' | 'success' | 'failed' | 'cancelled' | 'dry_run'

export interface FilterCard {
  kind: HistoryFilter
  title: string
  tone?: Tone
}

export const FILTER_CARDS: FilterCard[] = [
  { kind: 'all', title: '总记录' },
  { kind: 'success', title: '成功', tone: 'good' },
  { kind: 'failed', title: '失败', tone: 'warn' },
  { kind: 'cancelled', title: '已取消', tone: 'muted' },
  { kind: 'dry_run', title: '演练', tone: 'purple' },
]

export function filterTitle(kind: HistoryFilter): string {
  return FILTER_CARDS.find((card) => card.kind === kind)?.title ?? '总记录'
}

export type HistoryOutcome = 'success' | 'failed' | 'cancelled' | 'dry_run'

const OUTCOME_NAMES: Record<HistoryOutcome, string> = {
  success: '成功',
  failed: '失败',
  cancelled: '已取消',
  dry_run: '演练',
}

const OUTCOME_TONES: Record<HistoryOutcome, Tone> = {
  success: 'good',
  failed: 'warn',
  cancelled: 'muted',
  dry_run: 'purple',
}

// Result strings come from watch.log lines the backend stores verbatim; they are
// the only signal for old records without an `outcome` field.
const FAILED_HINTS = ['失败', '未知', '异常', '中止', '未提交', '没有买到', '额度不足']
const SUCCESS_HINTS = ['成功', '已提交', '成交']

export function outcomeName(outcome: HistoryOutcome): string {
  return OUTCOME_NAMES[outcome]
}

export function outcomeTone(outcome: HistoryOutcome): Tone {
  return OUTCOME_TONES[outcome]
}

/** One record's result class: 成功 / 失败 / 已取消 / 演练. */
export function outcomeOf(record: HistoryRecord): HistoryOutcome {
  if (record.dry_run || record.outcome === 'dry_run') return 'dry_run'
  if (record.phase === 'disarmed') return 'cancelled'
  if (record.phase === 'aborted') return 'failed'
  if (record.outcome === 'failed' || record.outcome === 'unknown') return 'failed'
  const result = record.result ?? ''
  if (FAILED_HINTS.some((hint) => result.includes(hint))) return 'failed'
  if (record.outcome === 'success' || SUCCESS_HINTS.some((hint) => result.includes(hint))) return 'success'
  return record.phase === 'done' ? 'success' : 'failed'
}

/**
 * A record the overview counts as a real task: drills (演练) never are, and the
 * saved favourite test item's product code is treated as a test code as well.
 */
export function isTestRecord(record: HistoryRecord, testCode?: string | null): boolean {
  if (record.dry_run || record.outcome === 'dry_run') return true
  return testCode ? record.code === testCode : false
}

export function realRecords(records: HistoryRecord[], testCode?: string | null): HistoryRecord[] {
  return records.filter((record) => !isTestRecord(record, testCode))
}

function timeOf(record: HistoryRecord): number {
  return parseLocal(record.ended_at ?? record.armed_at ?? record.at)?.getTime() ?? 0
}

/** Newest first; the API already does this, but tests and fixtures may not. */
export function sortNewest(records: HistoryRecord[]): HistoryRecord[] {
  return [...records].sort((a, b) => timeOf(b) - timeOf(a))
}

/**
 * The first screen's 近期布防 list: the latest real tasks that either succeeded or
 * failed, newest first, successes and failures mixed in one list.
 */
export function recentTasks(
  records: HistoryRecord[],
  testCode: string | null | undefined,
  limit = RECENT_LIMIT,
): HistoryRecord[] {
  return sortNewest(realRecords(records, testCode))
    .filter((record) => {
      const outcome = outcomeOf(record)
      return outcome === 'success' || outcome === 'failed'
    })
    .slice(0, limit)
}

export function matchFilter(record: HistoryRecord, kind: HistoryFilter): boolean {
  if (kind === 'all') return true
  return outcomeOf(record) === kind
}

export function filterRecords(records: HistoryRecord[], kind: HistoryFilter): HistoryRecord[] {
  return records.filter((record) => matchFilter(record, kind))
}

/** Stable selection key: task ids exist on records written by night_watch. */
export function recordKey(record: HistoryRecord): string {
  return (
    record.task_id ??
    `${record.armed_at ?? ''}|${record.code ?? ''}|${record.amount ?? ''}|${record.ended_at ?? ''}`
  )
}

export function modeText(record: HistoryRecord): string {
  if (record.mode === 'redemption') {
    return record.window_minutes ? `不定时抢购 · ${record.window_minutes} 分钟` : '不定时抢购'
  }
  return '首发'
}

/** "2026-11-09T09:00:18" → "09:00:18" for the compact card facts. */
export function clockText(value: unknown): string {
  const text = str(value)
  if (!text) return '—'
  const time = text.includes('T') ? text.split('T')[1] : text.split(' ')[1]
  return time ? time.slice(0, 8) : text
}

export function amountText(record: HistoryRecord): string {
  if (!record.amount) return '—'
  return /^\d+(\.\d+)?$/.test(record.amount) ? formatAmount(record.amount) : record.amount
}

export function resultText(record: HistoryRecord): string {
  const result = record.result?.trim()
  if (result) return result
  return outcomeOf(record) === 'success' ? '未记录结果' : '未记录失败原因'
}

const secondsBetween = (start: unknown, end: unknown): number | null => {
  const a = parseLocal(start)
  const b = parseLocal(end)
  if (!a || !b) return null
  const seconds = (b.getTime() - a.getTime()) / 1000
  return seconds >= 0 ? seconds : null
}

/** Duration strings for cards: `12.3 秒`, `2 分 05 秒`, `1 小时 3 分`. */
export function durationText(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return '—'
  if (seconds < 1) return `${Math.round(seconds * 1000)} 毫秒`
  if (seconds < 60) return `${seconds.toFixed(1)} 秒`
  const total = Math.round(seconds)
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const rest = total % 60
  if (hours) return `${hours} 小时 ${minutes} 分`
  return `${minutes} 分 ${String(rest).padStart(2, '0')} 秒`
}

/** Just the duration, for the compact card facts; the full line is in the detail panel. */
export function durationValue(record: HistoryRecord): string {
  const afterSubmit = secondsBetween(record.fired_at, record.ended_at)
  if (afterSubmit !== null) return durationText(afterSubmit)
  return durationText(secondsBetween(record.armed_at, record.ended_at))
}

/** 提交后… when the record fired, otherwise 全程… from arming to the end. */
export function durationLine(record: HistoryRecord): string {
  const afterSubmit = secondsBetween(record.fired_at, record.ended_at)
  if (afterSubmit !== null) return `提交后 ${durationText(afterSubmit)}`
  const total = secondsBetween(record.armed_at, record.ended_at)
  if (total !== null) return `全程 ${durationText(total)}`
  return '耗时未记录'
}

export function resumeCount(record: HistoryRecord): number {
  return record.resumes?.length ?? 0
}
