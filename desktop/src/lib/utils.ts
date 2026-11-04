import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'
import { z } from 'zod'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export const ACTIVE_PHASES = ['armed', 'preparing', 'waiting', 'firing']

const PHASE_NAMES: Record<string, string> = {
  armed: '已布防',
  preparing: '准备中',
  waiting: '盯盘中',
  firing: '正在提交',
  done: '已完成',
  aborted: '已中止',
  disarmed: '已取消',
}

export function phaseName(phase: string) {
  return PHASE_NAMES[phase] ?? phase
}

/** Tailwind text/bg tone for a phase: accent while live, good when done, warn when aborted. */
export function phaseTone(phase: string): Tone {
  if (['armed', 'waiting', 'firing'].includes(phase)) return 'accent'
  if (phase === 'preparing' || phase === 'aborted') return 'warn'
  if (phase === 'done') return 'good'
  return 'muted'
}

export type Tone = 'accent' | 'good' | 'warn' | 'muted' | 'blue' | 'purple'

export const toneText: Record<Tone, string> = {
  accent: 'text-accent',
  good: 'text-good',
  warn: 'text-warn',
  muted: 'text-muted',
  blue: 'text-blue',
  purple: 'text-purple',
}

export const toneBg: Record<Tone, string> = {
  accent: 'bg-accent',
  good: 'bg-good',
  warn: 'bg-warn',
  muted: 'bg-muted',
  blue: 'bg-blue',
  purple: 'bg-purple',
}

export function str(value: unknown): string | undefined {
  if (typeof value === 'string') return value
  if (typeof value === 'number') return String(value)
  return undefined
}

export function shortTime(value: unknown) {
  const text = str(value)
  if (!text) return '—'
  return text.replace('T', ' ').split('.')[0]
}

export function ageText(value: unknown) {
  if (typeof value !== 'number' || value < 0) return '—'
  if (value < 60) return `${Math.floor(value)} 秒前`
  if (value < 3600) return `${Math.floor(value / 60)} 分钟前`
  return `${Math.floor(value / 3600)} 小时前`
}

/** Parses the backend's naive local ISO time ("2026-11-05T09:00:00.200000") as local time. */
export function parseLocal(value: unknown): Date | null {
  const text = str(value)
  if (!text) return null
  const m = text.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/)
  if (!m) return null
  const [, y, mo, d, h, mi, s] = m.map(Number)
  return new Date(y, mo - 1, d, h, mi, s)
}

const pad = (n: number) => String(n).padStart(2, '0')

/** Formats as the backend's naive local ISO time, to the second. */
export function localISO(date: Date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

/** Value for <input type="datetime-local">. */
export function inputDateTime(date: Date) {
  return localISO(date).slice(0, 16)
}

export function clockTime(date: Date) {
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

export const codeSchema = z
  .string()
  .trim()
  .regex(/^[A-Za-z0-9]{4,20}$/, '产品代码须为 4–20 位字母或数字。')

export const amountSchema = z
  .string()
  .regex(/^[0-9]+(\.[0-9]{1,2})?$/, '金额须为 0–50000 元，最多两位小数。')
  .refine((v) => Number(v) > 0 && Number(v) <= 50_000, '金额须为 0–50000 元，最多两位小数。')

export const validCode = (text: string) => codeSchema.safeParse(text).success
export const validAmount = (text: string) => amountSchema.safeParse(text).success

export async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const area = document.createElement('textarea')
    area.value = text
    document.body.append(area)
    area.select()
    document.execCommand('copy')
    area.remove()
  }
}
