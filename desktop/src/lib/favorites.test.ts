import { describe, expect, it } from 'vitest'
import type { QuotaTime } from '../api/types'
import {
  emptyQuotaTime,
  isQuotaExpired,
  KIND_TEXT,
  KIND_TONE,
  MAX_AMOUNT_WAN,
  MAX_QUOTA_TIMES,
  NOTE_MAX,
  quotaAmountText,
  quotaEntriesOf,
  quotaTimeText,
  validAnnualized,
  validQuotaAmount,
  validQuotaDate,
  validQuotaTime,
  weekdayText,
} from './favorites'

/** Fixed clock: 2026-11-08 (Sunday) 12:00 local. Every time-dependent call passes it. */
const NOW = new Date(2026, 10, 8, 12, 0, 0)

function quota(overrides: Partial<QuotaTime> = {}): QuotaTime {
  return { kind: 'regular', time: '09:00', weekdays: [1], ...overrides }
}

describe('constants', () => {
  it('mirrors the backend caps', () => {
    expect(MAX_QUOTA_TIMES).toBe(50)
    expect(NOTE_MAX).toBe(100)
    expect(MAX_AMOUNT_WAN).toBe(1_000_000)
  })

  it('names and tones every kind', () => {
    expect(KIND_TEXT).toEqual({ issue: '首发', bargain: '捡漏', regular: '常规' })
    expect(KIND_TONE).toEqual({ issue: 'warn', bargain: 'purple', regular: 'blue' })
  })
})

describe('weekdayText', () => {
  it('prints nothing without weekdays', () => {
    expect(weekdayText([])).toBe('')
  })

  it('prints 每天 only for all seven days', () => {
    expect(weekdayText([1, 2, 3, 4, 5, 6, 7])).toBe('每天')
    expect(weekdayText([7, 6, 5, 4, 3, 2, 1])).toBe('每天')
    expect(weekdayText([1, 2, 3, 4, 5, 6])).toBe('周一～周六')
    expect(weekdayText([2, 3, 4])).toBe('周二～周四')
  })

  it('names a single day', () => {
    expect(weekdayText([1])).toBe('周一')
    expect(weekdayText([7])).toBe('周日')
  })

  it('lists gaps in ISO order', () => {
    expect(weekdayText([5, 1, 3])).toBe('周一、周三、周五')
    expect(weekdayText([1, 7])).toBe('周一、周日')
    expect(weekdayText([2, 4, 6, 7])).toBe('周二、周四、周六、周日')
  })

  it('sorts, dedupes and drops out-of-range values', () => {
    expect(weekdayText([2, 1, 2])).toBe('周一～周二')
    expect(weekdayText([0, 8, 2])).toBe('周二')
    expect(weekdayText([1.5, 3])).toBe('周三')
  })
})

describe('quotaTimeText', () => {
  it('formats 首发 with MM-DD within the same year', () => {
    expect(quotaTimeText(quota({ kind: 'issue', date: '2026-11-07', time: '09:00' }), NOW)).toBe(
      '11-07 09:00',
    )
    expect(quotaTimeText(quota({ kind: 'issue', date: '2026-01-02', time: '00:15' }), NOW)).toBe(
      '01-02 00:15',
    )
  })

  it('adds the year for 首发 in another year', () => {
    expect(quotaTimeText(quota({ kind: 'issue', date: '2025-12-31', time: '09:00' }), NOW)).toBe(
      '2025-12-31 09:00',
    )
    expect(quotaTimeText(quota({ kind: 'issue', date: '2027-01-01', time: '23:59' }), NOW)).toBe(
      '2027-01-01 23:59',
    )
  })

  it('formats weekly entries as weekdays plus time', () => {
    expect(
      quotaTimeText(quota({ kind: 'bargain', weekdays: [1, 2, 3, 4, 5, 6], time: '00:15', date: null }), NOW),
    ).toBe('周一～周六 00:15')
    expect(quotaTimeText(quota({ kind: 'regular', weekdays: [1], time: '09:00' }), NOW)).toBe('周一 09:00')
    expect(quotaTimeText(quota({ kind: 'regular', weekdays: [1, 2, 3, 4, 5, 6, 7] }), NOW)).toBe('每天 09:00')
  })

  it('falls back to the time when a 首发 date is missing or invalid', () => {
    expect(quotaTimeText(quota({ kind: 'issue', date: null, time: '09:00' }), NOW)).toBe('09:00')
    expect(quotaTimeText(quota({ kind: 'issue', date: '2026-02-31', time: '09:00' }), NOW)).toBe('09:00')
    expect(quotaTimeText(quota({ kind: 'issue', date: 'nope', time: '09:00' }), NOW)).toBe('09:00')
  })
})

describe('quotaAmountText', () => {
  it('always shows the unit 万', () => {
    expect(quotaAmountText(quota({ amount_wan: '5000' }))).toBe('5000 万')
    expect(quotaAmountText(quota({ amount_wan: '0.5' }))).toBe('0.5 万')
    expect(quotaAmountText(quota({ amount_wan: '100' }))).toBe('100 万')
  })

  it('says 不定额度 when no amount is recorded', () => {
    expect(quotaAmountText(quota({ amount_wan: undefined }))).toBe('不定额度')
    expect(quotaAmountText(quota({ amount_wan: null }))).toBe('不定额度')
    expect(quotaAmountText(quota({ amount_wan: '  ' }))).toBe('不定额度')
  })
})

describe('isQuotaExpired', () => {
  it('compares 首发 date + time against the local clock', () => {
    expect(isQuotaExpired(quota({ kind: 'issue', date: '2026-11-08', time: '11:59' }), NOW)).toBe(true)
    expect(isQuotaExpired(quota({ kind: 'issue', date: '2026-11-07', time: '23:59' }), NOW)).toBe(true)
    expect(isQuotaExpired(quota({ kind: 'issue', date: '2026-11-08', time: '12:00' }), NOW)).toBe(false)
    expect(isQuotaExpired(quota({ kind: 'issue', date: '2026-11-08', time: '12:01' }), NOW)).toBe(false)
    expect(isQuotaExpired(quota({ kind: 'issue', date: '2026-12-01', time: '09:00' }), NOW)).toBe(false)
    expect(isQuotaExpired(quota({ kind: 'issue', date: '2025-11-08', time: '12:00' }), NOW)).toBe(true)
  })

  it('never expires weekly entries', () => {
    expect(isQuotaExpired(quota({ kind: 'bargain', weekdays: [1], time: '00:15' }), NOW)).toBe(false)
    expect(isQuotaExpired(quota({ kind: 'regular', weekdays: [1], time: '09:00' }), NOW)).toBe(false)
  })

  it('treats malformed dates and times as not expired', () => {
    expect(isQuotaExpired(quota({ kind: 'issue', date: '2026-02-31', time: '09:00' }), NOW)).toBe(false)
    expect(isQuotaExpired(quota({ kind: 'issue', date: '2026-11-01', time: '25:00' }), NOW)).toBe(false)
    expect(isQuotaExpired(quota({ kind: 'issue', date: null, time: '09:00' }), NOW)).toBe(false)
    expect(isQuotaExpired(quota({ kind: 'issue', date: '2026-11-01', time: '' }), NOW)).toBe(false)
  })
})

describe('quotaEntriesOf', () => {
  it('returns the saved list or an empty list', () => {
    const entries = [quota({ id: 'q1' })]
    expect(quotaEntriesOf({ code: 'JX040229', quota_times: entries })).toBe(entries)
    expect(quotaEntriesOf({ code: 'JX040229' })).toEqual([])
    expect(quotaEntriesOf({ code: 'JX040229', quota_times: [] })).toEqual([])
  })
})

describe('validation', () => {
  it('accepts HH:MM from 00:00 to 23:59', () => {
    for (const value of ['00:00', '09:05', '12:30', '23:59']) expect(validQuotaTime(value)).toBe(true)
    for (const value of ['24:00', '23:60', '9:05', '09:0', '09:00:00', '', ' ', null, undefined])
      expect(validQuotaTime(value)).toBe(false)
  })

  it('accepts real YYYY-MM-DD dates only', () => {
    for (const value of ['2026-11-08', '2024-02-29', '2026-01-01']) expect(validQuotaDate(value)).toBe(true)
    for (const value of ['2026-02-29', '2026-13-01', '2026-00-10', '2026-11-31', '2026-1-1', '', null])
      expect(validQuotaDate(value)).toBe(false)
  })

  it('accepts positive amounts in 万 with at most two decimals', () => {
    for (const value of ['0.01', '0.5', '100', '5000', '1000000', '01'])
      expect(validQuotaAmount(value)).toBe(true)
    for (const value of ['0', '0.001', '1000001', '-1', 'abc', '', '1.234', null])
      expect(validQuotaAmount(value)).toBe(false)
  })
})

describe('validAnnualized', () => {
  it('allows an empty value (not recorded)', () => {
    expect(validAnnualized('')).toBe(true)
    expect(validAnnualized('   ')).toBe(true)
  })

  it('accepts percentages with an optional trailing % and at most two decimals', () => {
    for (const value of ['2.85', '2.85%', '3.1', '3.10', '0', '-0.5', '2', ' 2.85% '])
      expect(validAnnualized(value)).toBe(true)
  })

  it('accepts the -100..1000 bounds inclusively', () => {
    for (const value of ['-100', '-100.00%', '1000', '1000.00%']) expect(validAnnualized(value)).toBe(true)
    for (const value of ['-100.01', '1000.01', '2000', '-101', '1000.1'])
      expect(validAnnualized(value)).toBe(false)
  })

  it('rejects malformed numbers', () => {
    for (const value of [
      'abc',
      '3.123',
      '2.85%%',
      '%',
      '.5',
      '-.5',
      '+2.85',
      '2,85',
      '1e3',
      '2.85 %',
      '2.',
      '-',
      '--1',
    ])
      expect(validAnnualized(value)).toBe(false)
  })
})

describe('emptyQuotaTime', () => {
  it('creates the documented default row', () => {
    expect(emptyQuotaTime()).toEqual({ kind: 'regular', time: '09:00', weekdays: [1] })
  })
})
