import { describe, expect, it } from 'vitest'
import { readProgress, STEPS } from './progress'

// Real watch.log lines from the 11-05 11:06 drill (133045A, 0.01).
const DRILL = [
  '11-05 09:00:43 通知：结果未知',
  '11-05 11:03:00 通知：值守已开始：133045A 0.01 元，开售 11-05 11:06:00（演练）',
  '11-05 11:03:00 开始准备：冷启动并登录',
  '11-05 11:03:12 输入图案（第 1/3 次）',
  '已发送登录手势（约 5.3 秒）；请在模拟器确认登录结果。',
  '11-05 11:03:23 通知：登录成功（第 1 次图案）',
  'uia2 已连接并预热 0.06s',
  '11-05 11:03:25 通知：购买页已就绪，queryBuy 已挂起',
  '11-05 11:06:00 queryBuy 累计查询 1 次',
  '11-05 11:06:00 queryBuy 第 1 次：有额度，往返 305 ms',
  '11-05 11:06:00 queryBuy 有额度，表单已就绪（11:06:00.810）',
  '购买页显示单笔可购买额度 50000000 元（本次 0.01 元）',
  'JS 风险确认完成：原预检查、资料加载及文本校验通过，密码面板已请求。',
  '数字键盘就绪：焦点与10键可用，布局连续稳定 235ms。',
  '交易密码输入：第 1/2 轮',
  '演练：密码已输入，确定可点；未点确定。',
  '演练：输完密码约 1.85 秒；未点确定、未提交，已关闭密码框。',
  '11-05 11:06:03 耗时（毫秒，从有额度起）：表单复核 +60，风险确认 +711，密码页 +1101，输完密码（演练，未点确定） +1853',
  '11-05 11:06:03 通知：演练完成',
]
const ids = (states: string[], state: string) => STEPS.filter((_, i) => states[i] === state).map((s) => s.id)

describe('readProgress', () => {
  it('follows a whole drill in execution order and skips P12', () => {
    const p = readProgress(DRILL, 'done', true)
    expect(ids(p.states, 'done')).toEqual(STEPS.slice(0, 11).map((s) => s.id))
    expect(ids(p.states, 'skipped')).toEqual(['P12'])
    expect(p.active).toBe(-1)
    expect(p.queries).toEqual([{ attempt: 1, outcome: '有额度', ms: 305 }])
    expect(p.offsets).toEqual({ P9: 60, P10: 711, P11: 1853 })
    expect(p.finishedAt.P3).toBe('11:03:23')
  })

  it('reads only the latest task in the log window', () => {
    const p = readProgress(DRILL.slice(0, 3), 'preparing', true)
    expect(STEPS[p.active].id).toBe('P3')
    expect(p.queries).toEqual([])
  })

  it('puts P4 after P6: the warm-up line finishes the purchase page steps', () => {
    const p = readProgress(DRILL.slice(0, 7), 'preparing', true)
    expect(ids(p.states, 'done')).toEqual(['P1', 'P2', 'P3', 'P5', 'P6'])
    expect(STEPS[p.active].id).toBe('P4')
  })

  it('stays on P7 while queries come back sold out, listing each one', () => {
    const lines = [
      ...DRILL.slice(1, 8),
      '11-05 09:00:00 queryBuy 第 1 次：售罄，往返 180 ms',
      '11-05 09:00:00 queryBuy 第 2 次：售罄，往返 210 ms',
    ]
    const p = readProgress(lines, 'waiting')
    expect(STEPS[p.active].id).toBe('P7')
    expect(p.queries.map((q) => q.ms)).toEqual([180, 210])
  })

  it('a real purchase runs P12 and finishes on the result line', () => {
    const lines = [
      ...DRILL.slice(1, 12),
      '11-05 09:00:19 本次购买表单已校验，进入单次购买流程',
      'JS 风险确认完成：原预检查、资料加载及文本校验通过，密码面板已请求。',
      '已提交一次，核心流程约 3.34 秒；等待结果。',
    ]
    const waiting = readProgress(lines, 'firing')
    expect(STEPS[waiting.active].id).toBe('P12')
    const done = readProgress([...lines, '结果页提示：购买失败：额度不足'], 'done')
    expect(done.states.every((s) => s === 'done')).toBe(true)
    expect(done.active).toBe(-1)
  })

  it('marks the running step failed when the watch stops', () => {
    const p = readProgress([...DRILL.slice(1, 4), '11-05 11:03:40 通知：值守中止，未提交'], 'aborted')
    expect(p.states[2]).toBe('failed')
    expect(p.active).toBe(-1)
  })

  it('falls back to the phase when the task start has scrolled out of the log', () => {
    expect(STEPS[readProgress(['心跳'], 'waiting').active].id).toBe('P7')
    expect(
      readProgress([], 'firing')
        .states.slice(0, 9)
        .every((s) => s === 'done'),
    ).toBe(true)
  })
})
