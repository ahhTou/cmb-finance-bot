import { describe, expect, it } from 'vitest'
import type { Plan, PlanItem } from '../api/types'
import {
  countdownText,
  draftFromPlan,
  draftItemProblem,
  draftProblems,
  emptyDraftItem,
  isoClock,
  isoToItemInput,
  itemInputToISO,
  itemStateName,
  itemStateTone,
  itemStatus,
  nextItem,
  planDirty,
  planPhaseName,
  planPhaseTone,
  planStatus,
  planTotals,
  statusPrimaryName,
  statusPrimaryTone,
  statusSecondaryName,
} from './plan'

function item(overrides: Partial<PlanItem> = {}): PlanItem {
  return {
    item_id: 'item-1',
    code: 'JX040229',
    amount: '1000',
    at: '2026-11-07T09:00:00',
    mode: 'first_launch',
    state: 'pending',
    ...overrides,
  }
}

function plan(items: PlanItem[], overrides: Partial<Plan> = {}): Plan {
  return { dry_run: false, phase: 'idle', items, ...overrides }
}

describe('item states', () => {
  it('names and tones every state', () => {
    expect(itemStateName('pending')).toBe('待执行')
    expect(itemStateName('running')).toBe('执行中')
    expect(itemStateName('done')).toBe('已完成')
    expect(itemStateName('failed')).toBe('失败')
    expect(itemStateName('skipped')).toBe('跳过')
    expect(itemStateName(null)).toBe('待执行')
    expect(itemStateName('oddity')).toBe('oddity')
    expect(itemStateTone('running')).toBe('accent')
    expect(itemStateTone('done')).toBe('good')
    expect(itemStateTone('failed')).toBe('warn')
    expect(itemStateTone('pending')).toBe('muted')
  })

  it('names and tones every plan phase, including no plan', () => {
    expect(planPhaseName(null)).toBe('未计划')
    expect(planPhaseName('idle')).toBe('待开始')
    expect(planPhaseName('running')).toBe('运行中')
    expect(planPhaseName('paused')).toBe('已暂停')
    expect(planPhaseName('done')).toBe('已完成')
    expect(planPhaseName('aborted')).toBe('已中止')
    expect(planPhaseName('disarmed')).toBe('已取消')
    expect(planPhaseTone('running')).toBe('accent')
    expect(planPhaseTone('paused')).toBe('warn')
    expect(planPhaseTone('done')).toBe('good')
    expect(planPhaseTone('aborted')).toBe('warn')
    expect(planPhaseTone(null)).toBe('muted')
  })
})

describe('status model', () => {
  const now = new Date(2026, 10, 7, 10, 0, 0)

  it('names and colors every primary status', () => {
    expect(statusPrimaryName(null)).toBe('未计划')
    expect(statusPrimaryName({ primary: 'pending', secondary: 'scheduled' })).toBe('待开始')
    expect(statusPrimaryName({ primary: 'running', secondary: 'waiting' })).toBe('运行中')
    expect(statusPrimaryName({ primary: 'expired', secondary: 'time_passed' })).toBe('已过期')
    expect(statusPrimaryTone({ primary: 'running', secondary: 'waiting' })).toBe('accent')
    expect(statusPrimaryTone({ primary: 'done', secondary: 'success' })).toBe('good')
    expect(statusPrimaryTone({ primary: 'failed', secondary: 'purchase_failed' })).toBe('warn')
    expect(statusSecondaryName({ primary: 'failed', secondary: 'result_unknown' })).toBe('结果未知')
    expect(statusSecondaryName({ primary: 'pending', secondary: 'paused' })).toBe('已暂停')
  })

  it('falls back to expired for a pending item whose time passed', () => {
    const past = item({ at: '2026-11-07T09:00:00' })
    expect(itemStatus(past, now)).toMatchObject({ primary: 'expired', secondary: 'time_passed' })
    expect(itemStatus(item({ at: '2026-11-07T11:00:00' }), now)).toMatchObject({
      primary: 'pending',
      secondary: 'scheduled',
    })
  })

  it('falls back to a plan status when the backend has not supplied one', () => {
    expect(planStatus(null, now)).toBeNull()
    expect(planStatus(plan([], { phase: 'idle' }), now)).toMatchObject({
      primary: 'pending',
      secondary: 'scheduled',
    })
    expect(planStatus(plan([item({ at: '2026-11-07T09:00:00' })], { phase: 'idle' }), now)).toMatchObject({
      primary: 'expired',
      secondary: 'time_passed',
    })
    expect(planStatus(plan([], { phase: 'disarmed' }), now)).toMatchObject({
      primary: 'cancelled',
      secondary: 'manual_cancel',
    })
    expect(planStatus(plan([], { phase: 'paused' }), now)).toMatchObject({
      primary: 'pending',
      secondary: 'paused',
      description: '计划已暂停',
    })
  })
})

describe('nextItem', () => {
  it('prefers the running item, then the first pending one', () => {
    const running = item({ item_id: 'b', state: 'running' })
    const pending = item({ item_id: 'c', state: 'pending' })
    expect(nextItem(plan([item({ state: 'done' }), running, pending]))).toBe(running)
    expect(nextItem(plan([item({ state: 'done' }), pending]))).toBe(pending)
  })

  it('returns null with no plan, no items or nothing left', () => {
    expect(nextItem(null)).toBeNull()
    expect(nextItem(undefined)).toBeNull()
    expect(nextItem(plan([]))).toBeNull()
    expect(nextItem(plan([item({ state: 'done' }), item({ state: 'skipped' })]))).toBeNull()
  })
})

describe('countdownText', () => {
  const now = new Date(2026, 10, 6, 10, 0, 0)

  it('handles missing and already-reached times', () => {
    expect(countdownText(null, now)).toBe('—')
    expect(countdownText('', now)).toBe('—')
    expect(countdownText('nope', now)).toBe('—')
    expect(countdownText('2026-11-06T10:00:00', now)).toBe('已到时间')
    expect(countdownText('2026-11-06T09:59:59', now)).toBe('已到时间')
  })

  it('counts seconds, minutes and hours', () => {
    expect(countdownText('2026-11-06T10:00:42', now)).toBe('42 秒后')
    expect(countdownText('2026-11-06T10:07:32', now)).toBe('07:32 后')
    expect(countdownText('2026-11-06T13:05:00', now)).toBe('03:05 后')
  })

  it('crosses midnight and multiple days', () => {
    expect(countdownText('2026-11-07T00:30:00', now)).toBe('14:30 后')
    expect(countdownText('2026-11-08T00:30:00', now)).toBe('1 天 14:30 后')
  })
})

describe('planTotals', () => {
  it('counts items and sums the cents exactly', () => {
    expect(planTotals(null)).toEqual({ count: 0, amount: '0.00' })
    expect(planTotals(plan([]))).toEqual({ count: 0, amount: '0.00' })
    expect(planTotals(plan([item({ amount: '1000' })]))).toEqual({ count: 1, amount: '1,000.00' })
    expect(
      planTotals(plan([item({ amount: '1000' }), item({ amount: '0.01' }), item({ amount: '20000.50' })])),
    ).toEqual({ count: 3, amount: '21,000.51' })
  })

  it('ignores malformed amounts instead of producing NaN', () => {
    expect(planTotals(plan([item({ amount: 'x' }), item({ amount: '2' })]))).toEqual({
      count: 2,
      amount: '2.00',
    })
  })
})

describe('datetime-local conversions', () => {
  it('normalises the input value to backend ISO seconds', () => {
    expect(itemInputToISO('2026-11-07T09:00')).toBe('2026-11-07T09:00:00')
    expect(itemInputToISO('2026-11-07T09:00:30')).toBe('2026-11-07T09:00:30')
    expect(itemInputToISO(' 2026-11-07T09:00 ')).toBe('2026-11-07T09:00:00')
    expect(itemInputToISO('')).toBe('')
    expect(itemInputToISO('2026-11-07')).toBe('')
    expect(itemInputToISO('09:00')).toBe('')
  })

  it('drops seconds and microseconds for the input', () => {
    expect(isoToItemInput('2026-11-07T09:00:00')).toBe('2026-11-07T09:00')
    expect(isoToItemInput('2026-11-07T09:00:00.123456')).toBe('2026-11-07T09:00')
    expect(isoToItemInput('2026-11-07 09:00:00')).toBe('2026-11-07T09:00')
    expect(isoToItemInput(null)).toBe('')
    expect(isoToItemInput('nope')).toBe('')
    expect(itemInputToISO(isoToItemInput('2026-11-07T09:00:00'))).toBe('2026-11-07T09:00:00')
  })

  it('shows HH:MM for computed times', () => {
    expect(isoClock('2026-11-07T08:53:00')).toBe('08:53')
    expect(isoClock('2026-11-07T08:53:00.123456')).toBe('08:53')
    expect(isoClock(null)).toBe('—')
    expect(isoClock('nope')).toBe('—')
  })
})

describe('draft rows', () => {
  it('seeds editable rows from a saved plan', () => {
    const rows = draftFromPlan(plan([item({ mode: 'redemption', at: '2026-11-07T09:15:00' })]))
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({
      code: 'JX040229',
      amount: '1000',
      at: '2026-11-07T09:15',
      mode: 'redemption',
    })
    expect(rows[0].saved?.state).toBe('pending')
    expect(draftFromPlan(null)).toEqual([])
  })

  it('reports the first local format issue per row', () => {
    expect(draftItemProblem(emptyDraftItem())).toBe('请填写产品代码。')
    expect(draftItemProblem({ ...emptyDraftItem(), code: 'x' })).toContain('4–20')
    expect(draftItemProblem({ ...emptyDraftItem(), code: 'JX040229' })).toContain('金额')
    expect(draftItemProblem({ ...emptyDraftItem(), code: 'JX040229', amount: '60000', at: '' })).toBe(
      '请选择购买时间。',
    )
    expect(
      draftItemProblem({ ...emptyDraftItem(), code: 'JX040229', amount: '60000', at: '2026-11-07T09:00' }),
    ).toBeNull()
    expect(draftProblems([{ ...emptyDraftItem(), code: 'x' }])).toEqual([
      '第 1 项：产品代码须为 4–20 位字母或数字。',
    ])
  })

  it('tells saved plans from unsaved edits', () => {
    const saved = plan([item()])
    const rows = draftFromPlan(saved)
    expect(planDirty([], false, null)).toBe(false)
    expect(planDirty(rows, false, saved)).toBe(false)
    expect(planDirty(rows, true, saved)).toBe(true)
    expect(planDirty(rows, false, plan([item()], { dry_run: true }))).toBe(true)
    expect(planDirty([...rows, emptyDraftItem()], false, saved)).toBe(true)
    expect(planDirty([{ ...rows[0], amount: '2000' }], false, saved)).toBe(true)
    expect(planDirty([{ ...rows[0], at: '2026-11-07T09:01' }], false, saved)).toBe(true)
    expect(planDirty(draftFromPlan(null), false, null)).toBe(false)
  })
})
