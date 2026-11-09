import { describe, expect, it } from 'vitest'
import type { HistoryRecord } from '../api/types'
import {
  amountText,
  clockText,
  durationLine,
  durationText,
  durationValue,
  filterRecords,
  isTestRecord,
  matchFilter,
  modeText,
  outcomeOf,
  realRecords,
  recentRecords,
  recordKey,
  resultText,
  resumeCount,
  sortNewest,
} from './history'

const record = (over: Partial<HistoryRecord>): HistoryRecord => ({
  code: '135002A',
  amount: '5000',
  at: '2026-11-09T09:00:00',
  armed_at: '2026-11-09T08:51:00',
  ended_at: '2026-11-09T09:00:30',
  phase: 'done',
  ...over,
})

describe('outcomeOf', () => {
  it('reads an explicit outcome first', () => {
    expect(outcomeOf(record({ outcome: 'success' }))).toBe('success')
    expect(outcomeOf(record({ outcome: 'failed' }))).toBe('failed')
    expect(outcomeOf(record({ outcome: 'unknown' }))).toBe('failed')
    expect(outcomeOf(record({ outcome: 'dry_run' }))).toBe('dry_run')
  })
  it('falls back to the stored result text for old records', () => {
    expect(outcomeOf(record({ result: '提交成功' }))).toBe('success')
    expect(outcomeOf(record({ result: '已提交一次，核心流程约 2.04 秒' }))).toBe('success')
    expect(outcomeOf(record({ result: '结果未知，请查交易记录' }))).toBe('failed')
    expect(outcomeOf(record({ result: '购买失败：额度不足' }))).toBe('failed')
    expect(outcomeOf(record({ phase: 'aborted', result: '窗口内无额度' }))).toBe('failed')
  })
  it('keeps drills and cancellations out of success/failure', () => {
    expect(outcomeOf(record({ dry_run: true, result: '演练完成' }))).toBe('dry_run')
    expect(outcomeOf(record({ phase: 'disarmed' }))).toBe('cancelled')
  })
})

describe('real task filtering', () => {
  const testItem = '133045A'
  const records = [
    record({ code: '135002A', outcome: 'success' }),
    record({ code: '133045A', amount: '0.01', outcome: 'success' }),
    record({ code: 'GS110021', dry_run: true, outcome: 'dry_run' }),
    record({ phase: 'aborted', code: '120084A', outcome: 'failed' }),
  ]

  it('treats drills and the saved test code as tests', () => {
    expect(isTestRecord(records[1], testItem)).toBe(true)
    expect(isTestRecord(records[2], testItem)).toBe(true)
    expect(isTestRecord(records[0], testItem)).toBe(false)
    expect(isTestRecord(records[1], null)).toBe(false)
  })

  it('keeps only real tasks', () => {
    expect(realRecords(records, testItem).map((row) => row.code)).toEqual(['135002A', '120084A'])
  })

  it('lists recent successes and failures newest first, limited', () => {
    const successes = [
      record({ code: 'A', ended_at: '2026-11-01T09:00:00' }),
      record({ code: 'B', ended_at: '2026-11-03T09:00:00' }),
      record({ code: 'C', ended_at: '2026-11-02T09:00:00' }),
      record({ code: 'D', ended_at: '2026-11-04T09:00:00' }),
    ]
    expect(recentRecords(successes, null, 'success').map((row) => row.code)).toEqual(['D', 'B', 'C'])
    expect(recentRecords(successes, null, 'failed')).toEqual([])
  })

  it('sorts newest first without mutating the input', () => {
    const older = record({ code: '120084A', ended_at: '2026-11-08T09:00:00' })
    const newer = record({ code: '135002A', ended_at: '2026-11-09T09:00:30' })
    const rows = [older, newer]
    const sorted = sortNewest(rows)
    expect(sorted.map((row) => row.code)).toEqual(['135002A', '120084A'])
    expect(rows[0]).toBe(older)
  })
})

describe('type filters', () => {
  const records = [
    record({ phase: 'done' }),
    record({ phase: 'aborted' }),
    record({ phase: 'disarmed' }),
    record({ phase: 'done', result: '结果未知，请查交易记录' }),
    record({ dry_run: true, phase: 'done' }),
  ]
  it('matches the metric card kinds as a partition of the records', () => {
    expect(filterRecords(records, 'all')).toHaveLength(5)
    expect(filterRecords(records, 'success')).toHaveLength(1)
    expect(filterRecords(records, 'failed')).toHaveLength(2)
    expect(filterRecords(records, 'cancelled')).toHaveLength(1)
    expect(filterRecords(records, 'dry_run')).toHaveLength(1)
    expect(matchFilter(records[0], 'all')).toBe(true)
    expect(matchFilter(records[2], 'dry_run')).toBe(false)
    // A done record whose result is unknown counts as failed, not success.
    expect(filterRecords(records, 'failed')).toContain(records[3])
  })
})

describe('record presentation', () => {
  it('formats durations', () => {
    expect(durationText(null)).toBe('—')
    expect(durationText(0.42)).toBe('420 毫秒')
    expect(durationText(2.44)).toBe('2.4 秒')
    expect(durationText(125)).toBe('2 分 05 秒')
    expect(durationText(3900)).toBe('1 小时 5 分')
  })

  it('prefers the submit-to-end duration', () => {
    expect(durationLine(record({ fired_at: '2026-11-09T09:00:18', ended_at: '2026-11-09T09:00:30' }))).toBe(
      '提交后 12.0 秒',
    )
    expect(durationLine(record({ armed_at: '2026-11-09T08:50:00' }))).toBe('全程 10 分 30 秒')
    expect(durationValue(record({ fired_at: '2026-11-09T09:00:18', ended_at: '2026-11-09T09:00:30' }))).toBe(
      '12.0 秒',
    )
    expect(durationValue(record({ armed_at: '2026-11-09T08:50:00' }))).toBe('10 分 30 秒')
    expect(durationLine(record({ armed_at: undefined, ended_at: undefined }))).toBe('耗时未记录')
  })

  it('names modes, amounts and results', () => {
    expect(modeText(record({ mode: 'redemption', window_minutes: 2 }))).toBe('不定时抢购 · 2 分钟')
    expect(modeText(record({ mode: 'redemption' }))).toBe('不定时抢购')
    expect(modeText(record({ mode: 'first_launch' }))).toBe('首发')
    expect(clockText('2026-11-09T09:00:18')).toBe('09:00:18')
    expect(clockText('2026-11-09 09:00:18')).toBe('09:00:18')
    expect(clockText(undefined)).toBe('—')
    expect(amountText(record({ amount: '5000' }))).toBe('5,000.00')
    expect(amountText(record({ amount: undefined }))).toBe('—')
    expect(resultText(record({ result: '提交成功' }))).toBe('提交成功')
    expect(resultText(record({ result: ' ' }))).toBe('未记录结果')
    expect(resultText(record({ phase: 'aborted', result: null }))).toBe('未记录失败原因')
  })

  it('keys selections by task id when present', () => {
    expect(recordKey(record({ task_id: 't1' }))).toBe('t1')
    expect(recordKey(record({ code: 'X' }))).toBe('2026-11-09T08:51:00|X|5000|2026-11-09T09:00:30')
    expect(resumeCount(record({ resumes: [{ at: '2026-11-09T09:00:00' }] }))).toBe(1)
    expect(resumeCount(record({}))).toBe(0)
  })
})
