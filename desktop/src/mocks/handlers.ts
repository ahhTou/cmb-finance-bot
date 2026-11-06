import { delay, HttpResponse, http } from 'msw'
import type { ArmRequest, CancelRequest, Favorite, Mode, Plan, PlanItem, PlanView, Task } from '../api/types'
import { localISO, parseLocal } from '../lib/utils'
import {
  DEVICE,
  DRILL_SCRIPT,
  FAVORITES,
  HISTORY,
  LOG_LINES,
  makePlan,
  makeStatus,
  makeTask,
  SETTINGS,
  SYSTEM,
  scenario,
} from './fixtures'

/** In-memory backend so arming, disarming and favorites behave like the real one. */
const kind = scenario()
const state = {
  task: makeTask(kind),
  favorites: kind === 'empty' ? [] : FAVORITES.map((row) => ({ ...row })),
  logs: kind === 'empty' ? [] : [...LOG_LINES],
  history: kind === 'empty' ? [] : [...HISTORY],
  plan: makePlan(kind),
  planLogs:
    kind === 'plan'
      ? [`${localISO(new Date()).slice(5).replace('T', ' ')} 已保存计划：2 项（演练）`]
      : ([] as string[]),
}
const active = () => ['armed', 'preparing', 'waiting', 'firing'].includes(state.task?.phase ?? '')
const fail = (error: string, status = 400) => HttpResponse.json({ error }, { status })
const status = () => makeStatus(state.task, state.favorites, state.logs)
const planStamp = () => localISO(new Date()).slice(5).replace('T', ' ')

// ---- Plan mode (`/api/plan`) ------------------------------------------------
// Mirrors src/watch_plan.py: prep_at = at - cold start; first-launch end is the
// worst-case query window (90 s) plus a 2 min submit margin; redemption end is
// the configured window. Kept in sync with the real backend so the mock cannot
// hide a scheduling difference.
const PLAN_PREP_MINUTES = SETTINGS.cold_start_minutes
const PLAN_FIRST_END_MINUTES = 3.5
const PLAN_END_MINUTES: Record<Mode, number> = {
  first_launch: PLAN_FIRST_END_MINUTES,
  redemption: SETTINGS.irregular_window_minutes,
}
const planClock = (value: string) => /T(\d{2}:\d{2})/.exec(value)?.[1] ?? value

function planItemView(item: PlanItem): PlanItem {
  const at = parseLocal(item.at)
  if (!at) return { ...item }
  return {
    ...item,
    prep_at: localISO(new Date(at.getTime() - PLAN_PREP_MINUTES * 60_000)),
    end_at: localISO(new Date(at.getTime() + PLAN_END_MINUTES[item.mode] * 60_000)),
  }
}

function planProblems(plan: Plan): string[] {
  const items = plan.items
  if (!items.length) return ['计划里还没有布防。']
  const now = Date.now()
  const problems = items.flatMap((item, index) => {
    const at = parseLocal(item.at)
    if (!at) return [`第 ${index + 1} 项购买时间格式无效。`]
    if (at.getTime() <= now) return [`第 ${index + 1} 项购买时间已过（${planClock(item.at)}）。`]
    if (at.getTime() > now + 24 * 3600_000) return [`第 ${index + 1} 项购买时间超过 24 小时。`]
    return []
  })
  for (let index = 1; index < items.length; index += 1) {
    const previous = items[index - 1]
    const current = items[index]
    const previousAt = parseLocal(previous.at)
    const currentAt = parseLocal(current.at)
    if (!previousAt || !currentAt) continue
    const previousEnd = previousAt.getTime() + PLAN_END_MINUTES[previous.mode] * 60_000
    const currentPrep = currentAt.getTime() - PLAN_PREP_MINUTES * 60_000
    if (currentPrep >= previousEnd + 2 * 60_000) continue
    const minimum = Math.ceil(
      (previousEnd - previousAt.getTime() + (PLAN_PREP_MINUTES + 2) * 60_000) / 60_000,
    )
    problems.push(
      `第 ${index + 1} 项与第 ${index} 项间隔太近：第 ${index + 1} 项需在 ${planClock(localISO(new Date(currentPrep)))} 开始冷启动，但第 ${index} 项预计 ${planClock(localISO(new Date(previousEnd)))} 才结束；请把购买时间拉开到至少 ${minimum} 分钟。`,
    )
  }
  return problems
}

function planWarnings(plan: Plan): string[] {
  const first = plan.items[0]
  if (!first) return []
  const at = parseLocal(first.at)
  if (!at) return []
  const prepAt = at.getTime() - PLAN_PREP_MINUTES * 60_000
  if (Date.now() > prepAt - 2 * 60_000 && at.getTime() > Date.now())
    return ['第一项已进入冷启动时间，开始后将立即冷启动。']
  return []
}

function planView(): PlanView {
  const plan = state.plan
  const running = plan?.phase === 'running'
  return {
    plan: plan ? { ...plan, items: plan.items.map(planItemView) } : null,
    running,
    stale: false,
    problems: plan ? planProblems(plan) : [],
    warnings: plan ? planWarnings(plan) : [],
    task: state.task,
    log_path: '/mock/var/night/plan.log',
    logs: state.planLogs.slice(-15),
    settings_revision: 'mock-revision',
    now: localISO(new Date()),
  }
}

function savedPlan(dryRun: boolean, items: { code: string; amount: string; at: string; mode: Mode }[]): Plan {
  return {
    version: 1,
    plan_id: `mock-${Math.random().toString(16).slice(2, 10)}`,
    generation: null,
    created_at: localISO(new Date()),
    started_at: null,
    ended_at: null,
    dry_run: dryRun,
    phase: 'idle',
    pid: null,
    last_tick: null,
    settings_revision: 'mock-revision',
    result: null,
    items: items.map((item, index) => ({
      item_id: `mock-item-${index}-${Math.random().toString(16).slice(2, 8)}`,
      code: item.code.trim(),
      amount: item.amount.trim(),
      at: item.at,
      mode: item.mode,
      state: 'pending',
      task_id: null,
      result: null,
      armed_at: null,
      ended_at: null,
    })),
  }
}

// `progress`: replay the drill log line by line, then start over.
if (kind === 'progress') {
  let step = 0
  const next = () => {
    const [line, phase, pause] = DRILL_SCRIPT[step]
    state.logs.push(line())
    if (state.task) state.task = { ...state.task, phase }
    step = (step + 1) % DRILL_SCRIPT.length
    setTimeout(next, pause)
  }
  next()
}

// Keep the live log moving while a task is active.
setInterval(() => {
  if (active() && kind !== 'progress')
    state.logs.push(`${localISO(new Date()).slice(5).replace('T', ' ')} 心跳：购买页在线，等待查询`)
}, 2000)

export const handlers = [
  http.get('/api/status', async () => {
    await delay(120)
    return kind === 'error' ? fail('后端返回格式无效。', 502) : HttpResponse.json(status())
  }),
  http.get('/api/events', () => {
    const encoder = new TextEncoder()
    let timer: ReturnType<typeof setInterval>
    const stream = new ReadableStream({
      start(controller) {
        const send = () => {
          const chunk =
            kind === 'error'
              ? `event: failure\ndata: ${JSON.stringify({ error: '后端返回格式无效。' })}\n\n`
              : `event: status\ndata: ${JSON.stringify(status())}\n\n`
          controller.enqueue(encoder.encode(chunk))
        }
        send()
        timer = setInterval(send, 3000)
      },
      cancel() {
        clearInterval(timer)
      },
    })
    return new HttpResponse(stream, { headers: { 'Content-Type': 'text/event-stream' } })
  }),
  http.get('/api/info', () =>
    HttpResponse.json({
      root: '/mock/cmb-finance-bot',
      python: '/usr/bin/python3',
      log_path: '/mock/var/night/watch.log',
      skill_path: '/mock/cmb-finance-bot/skills/cmb-watch/SKILL.md',
    }),
  ),
  http.get('/api/device', async () => {
    await delay(300)
    return HttpResponse.json(DEVICE)
  }),
  http.get('/api/system', async () => {
    await delay(600)
    return HttpResponse.json(SYSTEM)
  }),
  http.get('/api/history', () =>
    HttpResponse.json({ records: state.history, total: state.history.length, shown: state.history.length }),
  ),
  http.get('/api/log', ({ request }) => {
    const lines = Number(new URL(request.url).searchParams.get('lines') ?? 800)
    return HttpResponse.json({
      path: '/mock/var/night/watch.log',
      lines: state.logs.slice(-lines),
      total: state.logs.length,
      exists: true,
    })
  }),
  http.get('/api/settings', () =>
    HttpResponse.json({ settings: SETTINGS, settings_revision: 'mock-revision' }),
  ),
  http.put('/api/settings', async ({ request }) => {
    Object.assign(SETTINGS, await request.json())
    return HttpResponse.json({ settings: SETTINGS, settings_revision: 'mock-revision' })
  }),
  http.post('/api/arm', async ({ request }) => {
    const body = (await request.json()) as ArmRequest
    await delay(800)
    if (active()) return fail('已有活动任务；先取消防守。')
    if (body.now && !body.dry_run && !body.confirm_real_payment)
      return fail('立即真实布防必须明确确认实际付款。')
    const at = body.now ? localISO(new Date(Date.now() + 3 * 60_000)) : (body.at ?? '')
    const task: Task = {
      code: body.code,
      amount: body.amount,
      at,
      fire_at: at,
      end_at: body.mode === 'redemption' ? localISO(new Date(+new Date(at) + 5 * 60_000)) : undefined,
      mode: body.mode,
      phase: 'armed',
      dry_run: body.dry_run,
      prep_minutes: body.prep_minutes ?? 7,
      window_minutes: body.mode === 'redemption' ? 5 : null,
      patterns_sent: 0,
      armed_at: localISO(new Date()),
    }
    state.task = task
    state.logs.push(
      `${localISO(new Date()).slice(5).replace('T', ' ')} 已布防 ${body.code} ${body.amount} 元`,
    )
    return HttpResponse.json({ task, ok: true })
  }),
  http.post('/api/disarm', async () => {
    await delay(400)
    if (state.task) state.task = { ...state.task, phase: 'disarmed' }
    return HttpResponse.json({ task: state.task, ok: true })
  }),
  http.post('/api/emulator/:action', async () => {
    await delay(700)
    return HttpResponse.json({ ok: true })
  }),
  http.post('/api/keep-awake', () => HttpResponse.json({ ok: true })),
  http.post('/api/screenshot', () => HttpResponse.json({ path: '/mock/current.png', ok: true })),
  http.get('/api/screenshot.png', async () => {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="640"><rect width="320" height="640" fill="#c8102e"/><text x="160" y="320" fill="#fff" font-size="28" text-anchor="middle">模拟器画面</text></svg>`
    return new HttpResponse(svg, { headers: { 'Content-Type': 'image/svg+xml' } })
  }),
  http.post('/api/buy', async ({ request }) => {
    const body = (await request.json()) as { code: string; amount: string; real: boolean }
    await delay(1200)
    if (active()) return fail('值守任务活动期间不能单笔购买或演练。')
    return HttpResponse.json({
      output: [
        `打开 ${body.code} 购买页`,
        `填写金额 ${body.amount}`,
        body.real ? '已提交一次' : '输完密码，未点确定，演练结束',
      ],
      ok: true,
    })
  }),
  http.post('/api/cancel', async ({ request }) => {
    const body = (await request.json()) as CancelRequest
    await delay(900)
    if (active()) return fail('值守任务活动期间不能撤单；先取消防守。')
    return HttpResponse.json({
      output: [`金额 ${body.amount} 元的可撤单订单：2 笔`, `动作：${body.action}`],
      ok: true,
    })
  }),
  http.get('/api/favorites', () => HttpResponse.json({ favorites: state.favorites })),
  http.post('/api/favorites', async ({ request }) => {
    const body = (await request.json()) as Favorite
    const existing = state.favorites.find((f) => f.code === body.code)
    if (existing) existing.title = body.title
    else state.favorites.push(body)
    return HttpResponse.json({ favorites: state.favorites, ok: true })
  }),
  http.post('/api/favorites/test', async ({ request }) => {
    const body = (await request.json()) as { code: string; amount: string }
    const row = state.favorites.find((f) => f.code.toLowerCase() === body.code.toLowerCase())
    if (!row) return fail('先收藏这个产品，再设为测试项。')
    for (const favorite of state.favorites) delete favorite.test_amount
    row.test_amount = body.amount
    return HttpResponse.json({ favorites: state.favorites, ok: true })
  }),
  http.delete('/api/favorites/test', () => {
    for (const favorite of state.favorites) delete favorite.test_amount
    return HttpResponse.json({ favorites: state.favorites, ok: true })
  }),
  http.delete('/api/favorites/:code', ({ params }) => {
    state.favorites = state.favorites.filter((f) => f.code !== params.code)
    return HttpResponse.json({ favorites: state.favorites, ok: true })
  }),
  http.post('/api/credentials/:kind', () => HttpResponse.json({ ok: true })),
  http.post('/api/open-log', () => HttpResponse.json({ ok: true })),
  // Plan mode: read, save (PUT), start, disarm, clear (DELETE).
  http.get('/api/plan', async () => {
    await delay(120)
    return HttpResponse.json(planView())
  }),
  http.put('/api/plan', async ({ request }) => {
    const body = (await request.json()) as {
      dry_run?: boolean
      items?: { code?: string; amount?: string; at?: string; mode?: Mode }[]
    }
    await delay(300)
    if (state.plan?.phase === 'running') return fail('计划正在运行，不能修改；先取消计划。')
    const items = body.items ?? []
    if (items.length > 20) return fail('计划最多 20 项。')
    for (const item of items) {
      if (!/^[A-Za-z0-9]{4,20}$/.test((item.code ?? '').trim()))
        return fail('产品代码须为 4–20 位字母或数字。')
      if (!/^[0-9]+(\.[0-9]{1,2})?$/.test((item.amount ?? '').trim()) || !(Number(item.amount) > 0))
        return fail('金额须为大于 0 的数字，最多两位小数。')
      if (!parseLocal(item.at)) return fail('购买时间格式无效。')
      if (item.mode !== 'first_launch' && item.mode !== 'redemption') return fail('购买模式无效。')
    }
    const sorted = [...items].sort((left, right) => (left.at ?? '').localeCompare(right.at ?? ''))
    state.plan = savedPlan(
      body.dry_run === true,
      sorted.map((item) => ({
        code: item.code ?? '',
        amount: item.amount ?? '',
        at: item.at ?? '',
        mode: item.mode === 'redemption' ? 'redemption' : 'first_launch',
      })),
    )
    state.planLogs.push(`${planStamp()} 已保存计划：${sorted.length} 项（${body.dry_run ? '演练' : '真实'}）`)
    return HttpResponse.json(planView())
  }),
  http.post('/api/plan/start', async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as { confirm_real_payment?: boolean }
    await delay(400)
    const plan = state.plan
    if (!plan) return fail('计划里还没有布防。')
    if (plan.phase === 'running') return fail('计划正在运行；先取消计划再开始。')
    if (plan.phase !== 'idle') return fail('计划已结束；请清空后重新保存再开始。')
    const problems = planProblems(plan)
    if (problems.length) return fail(problems[0])
    if (!plan.dry_run && !body.confirm_real_payment) return fail('真实计划必须明确确认实际付款。')
    const now = localISO(new Date())
    plan.phase = 'running'
    plan.started_at = now
    plan.last_tick = now
    plan.generation = Math.random().toString(16).slice(2, 10)
    plan.pid = 4242
    plan.items = plan.items.map((item, index) =>
      index === 0 ? { ...item, state: 'running', armed_at: now } : item,
    )
    state.planLogs.push(`${planStamp()} 计划已开始：${plan.items.length} 项`)
    state.planLogs.push(
      `${planStamp()} 第 1 项：${plan.items[0].code} ${plan.items[0].amount} 元，购买时间 ${planClock(plan.items[0].at)}`,
    )
    return HttpResponse.json(planView())
  }),
  http.post('/api/plan/disarm', async () => {
    await delay(300)
    const plan = state.plan
    if (plan?.phase !== 'running') return fail('计划没有在运行。')
    const now = localISO(new Date())
    plan.phase = 'disarmed'
    plan.ended_at = now
    plan.pid = null
    plan.result = '计划已被手动取消'
    plan.items = plan.items.map((item) =>
      item.state === 'running' || item.state === 'pending'
        ? {
            ...item,
            state: 'skipped',
            result: '计划已被手动取消',
            ended_at: now,
          }
        : item,
    )
    state.planLogs.push(`${planStamp()} 计划已取消`)
    return HttpResponse.json(planView())
  }),
  http.delete('/api/plan', async () => {
    await delay(200)
    if (state.plan?.phase === 'running') return fail('计划正在运行；先取消计划。')
    state.plan = null
    state.planLogs = []
    return HttpResponse.json(planView())
  }),
]
