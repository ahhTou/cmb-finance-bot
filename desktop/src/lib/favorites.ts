import type { Favorite, QuotaKind, QuotaTime } from '../api/types'
import type { Tone } from './utils'

// Same caps as src/favorites.py; the front end only mirrors them for the editor.
export const MAX_QUOTA_TIMES = 50
export const NOTE_MAX = 100
export const MAX_AMOUNT_WAN = 1_000_000

export const KIND_TEXT: Record<QuotaKind, string> = {
  issue: '首发',
  bargain: '捡漏',
  regular: '常规',
}

/** Badge tone per kind: 首发 warn, 捡漏 purple, 常规 blue. */
export const KIND_TONE: Record<QuotaKind, Tone> = {
  issue: 'warn',
  bargain: 'purple',
  regular: 'blue',
}

/** ISO weekday numbers: 1 = 周一 … 7 = 周日. */
export const WEEKDAY_TEXT: Record<number, string> = {
  1: '周一',
  2: '周二',
  3: '周三',
  4: '周四',
  5: '周五',
  6: '周六',
  7: '周日',
}

const ALL_WEEKDAYS = [1, 2, 3, 4, 5, 6, 7]

const pad2 = (value: number) => String(value).padStart(2, '0')

/**
 * Human text for ISO weekdays: `[]` → `''`, all seven → `每天`,
 * one consecutive run → `周一～周六`, otherwise `周一、周三、周五`.
 * Sorts, dedupes and drops out-of-range days so saved/edited data cannot print nonsense.
 */
export function weekdayText(days: number[]): string {
  const selected = [...new Set(days.filter((day) => Number.isInteger(day) && day >= 1 && day <= 7))].sort(
    (left, right) => left - right,
  )
  if (selected.length === 0) return ''
  if (selected.length === ALL_WEEKDAYS.length) return '每天'
  if (selected.length === 1) return WEEKDAY_TEXT[selected[0]]
  const consecutive = selected.every((day, index) => index === 0 || day === selected[index - 1] + 1)
  if (consecutive) return `${WEEKDAY_TEXT[selected[0]]}～${WEEKDAY_TEXT[selected[selected.length - 1]]}`
  return selected.map((day) => WEEKDAY_TEXT[day]).join('、')
}

function parseQuotaDate(value: string | null | undefined): Date | null {
  const text = (value ?? '').trim()
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text)
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  const date = new Date(year, month - 1, day)
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) return null
  return date
}

export function validQuotaTime(value: string | null | undefined): boolean {
  return typeof value === 'string' && /^([01]\d|2[0-3]):[0-5]\d$/.test(value.trim())
}

/** `YYYY-MM-DD` of a real calendar date; `2026-02-29` is rejected. */
export function validQuotaDate(value: string | null | undefined): boolean {
  return parseQuotaDate(value) !== null
}

/** 额度数 in 万: > 0, at most two decimals, at most 1,000,000. */
export function validQuotaAmount(value: string | null | undefined): boolean {
  if (typeof value !== 'string') return false
  const text = value.trim()
  if (!/^\d+(\.\d{1,2})?$/.test(text)) return false
  const amount = Number(text)
  return amount > 0 && amount <= MAX_AMOUNT_WAN
}

function issueMoment(entry: QuotaTime): Date | null {
  const date = parseQuotaDate(entry.date)
  if (!date || !validQuotaTime(entry.time)) return null
  const [hours, minutes] = entry.time.trim().split(':').map(Number)
  date.setHours(hours, minutes, 0, 0)
  return date
}

/**
 * True only for 首发 whose `date` + `time` is already in the past by local time.
 * Weekly entries never expire and malformed dates fall back to false (not expired).
 */
export function isQuotaExpired(entry: QuotaTime, now: Date = new Date()): boolean {
  if (entry.kind !== 'issue') return false
  const moment = issueMoment(entry)
  return moment !== null && moment.getTime() < now.getTime()
}

/** 首发 `MM-DD HH:MM` (with the year when it differs from `now`); weekly `周一～周六 00:15`. */
export function quotaTimeText(entry: QuotaTime, now: Date = new Date()): string {
  const time = entry.time?.trim() ?? ''
  if (entry.kind === 'issue') {
    const moment = issueMoment(entry)
    if (!moment) return time
    const day = `${pad2(moment.getMonth() + 1)}-${pad2(moment.getDate())}`
    return moment.getFullYear() === now.getFullYear()
      ? `${day} ${time}`
      : `${moment.getFullYear()}-${day} ${time}`
  }
  return `${weekdayText(entry.weekdays ?? [])} ${time}`.trim()
}

/** `5000 万`, or `不定额度` when the entry has no amount. */
export function quotaAmountText(entry: QuotaTime): string {
  const amount = entry.amount_wan?.trim()
  return amount ? `${amount} 万` : '不定额度'
}

/** The favourite's quota times; missing means none. */
export function quotaEntriesOf(favorite: Favorite): QuotaTime[] {
  return favorite.quota_times ?? []
}

/** A new editor row: 常规, 09:00, 周一, 不定额度, 空备注. */
export function emptyQuotaTime(): QuotaTime {
  return { kind: 'regular', time: '09:00', weekdays: [1] }
}
