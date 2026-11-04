import { describe, expect, it } from 'vitest'
import { ageText, localISO, parseLocal, phaseName, shortTime, validAmount, validCode } from './utils'

describe('time helpers', () => {
  it('reads the backend naive ISO time as local time', () => {
    const date = parseLocal('2026-11-05T09:00:00.200000')
    expect(date && localISO(date)).toBe('2026-11-05T09:00:00')
    expect(parseLocal('nope')).toBeNull()
    expect(parseLocal(undefined)).toBeNull()
  })

  it('shortens times and ages like the native app', () => {
    expect(shortTime('2026-11-05T09:00:00.200000')).toBe('2026-11-05 09:00:00')
    expect(shortTime(null)).toBe('—')
    expect(ageText(42.9)).toBe('42 秒前')
    expect(ageText(125)).toBe('2 分钟前')
    expect(ageText(7300)).toBe('2 小时前')
    expect(ageText(null)).toBe('—')
  })
})

describe('validation', () => {
  it('accepts product codes of 4–20 letters or digits', () => {
    expect(validCode('JX040229')).toBe(true)
    expect(validCode(' 133045A ')).toBe(true)
    expect(validCode('ab1')).toBe(false)
    expect(validCode('JX-0402')).toBe(false)
  })

  it('accepts amounts above 0 up to 50000 with at most two decimals', () => {
    expect(validAmount('0.01')).toBe(true)
    expect(validAmount('50000')).toBe(true)
    expect(validAmount('0')).toBe(false)
    expect(validAmount('50000.01')).toBe(false)
    expect(validAmount('1.234')).toBe(false)
    expect(validAmount('-1')).toBe(false)
  })
})

it('names phases', () => {
  expect(phaseName('waiting')).toBe('盯盘中')
  expect(phaseName('unknown')).toBe('unknown')
})
