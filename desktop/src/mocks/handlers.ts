import { delay, HttpResponse, http } from 'msw'
import type {
  ArmRequest,
  CancelRequest,
  Favorite,
  FavoriteSettingsRequest,
  Mode,
  Plan,
  PlanItem,
  PlanView,
  QuotaKind,
  QuotaTime,
  Task,
} from '../api/types'
import { MAX_QUOTA_TIMES } from '../lib/favorites'
import { localISO, parseLocal, validAmount } from '../lib/utils'
import {
  DEVICE,
  DRILL_SCRIPT,
  FAVORITES,
  HISTORY,
  LOG_LINES,
  makePlan,
  makePush,
  makeStatus,
  makeTask,
  PLAN_SETTINGS,
  SETTINGS,
  SYSTEM,
  scenario,
} from './fixtures'
import pushPreferencesDefaults from './push-preferences.json'

/** In-memory backend so arming, disarming and favorites behave like the real one. */
const kind = scenario()
const state = {
  task: makeTask(kind),
  favorites: kind === 'empty' ? [] : FAVORITES.map((row) => ({ ...row })),
  logs: kind === 'empty' ? [] : [...LOG_LINES],
  history: kind === 'empty' ? [] : [...HISTORY],
  plan: makePlan(kind),
  push: makePush(kind),
  pushPreferences: structuredClone(pushPreferencesDefaults),
  planSettings: structuredClone(PLAN_SETTINGS),
  planLogs:
    kind === 'plan'
      ? [`${localISO(new Date()).slice(5).replace('T', ' ')} 已保存计划：2 项（演练）`]
      : ([] as string[]),
}
const active = () => ['armed', 'preparing', 'waiting', 'firing'].includes(state.task?.phase ?? '')
const fail = (error: string, status = 400) => HttpResponse.json({ error }, { status })

// Favourite settings (var/favorites-v2-contract.md §1/§4): the mock mirrors the
// server's canonical rows — kept ids, full-list replacement, generated ids,
// empty fields omitted, at most one test item.
const quotaId = () => `q${Math.random().toString(16).slice(2, 12).padEnd(10, '0')}`

function normalizeQuotaTime(entry: QuotaTime, used: Set<string>): QuotaTime {
  const kind: QuotaKind =
    entry.kind === 'issue' || entry.kind === 'bargain' || entry.kind === 'regular' ? entry.kind : 'regular'
  const id = entry.id && /^[A-Za-z0-9_-]{1,24}$/.test(entry.id) && !used.has(entry.id) ? entry.id : quotaId()
  used.add(id)
  const normalized: QuotaTime = { id, kind, time: String(entry.time ?? '') }
  if (kind === 'issue') normalized.date = String(entry.date ?? '')
  else {
    normalized.weekdays = [...new Set(entry.weekdays ?? [])]
      .filter((day) => day >= 1 && day <= 7)
      .sort((left, right) => left - right)
  }
  const amount = (entry.amount_wan ?? '').trim()
  if (amount) normalized.amount_wan = amount
  const note = (entry.note ?? '').trim()
  if (note) normalized.note = note
  return normalized
}

/**
 * Mock counterpart of the server's 近期年化 normalisation: numeric text becomes
 * two decimals plus '%' (`3.1` → `3.10%`); other text is kept verbatim so a bad
 * test payload is not silently rewritten.
 */
function annualizedText(value: string): string {
  const match = /^(-?\d+)(?:\.(\d{1,2}))?%?$/.exec(value.trim())
  if (!match) return value.trim()
  const number = Number(`${match[1]}${match[2] ? `.${match[2]}` : ''}`)
  return `${number.toFixed(2)}%`
}

const status = () => ({
  ...makeStatus(state.task, state.favorites, state.logs),
  push_configured: state.push.configured,
})
const planStamp = () => localISO(new Date()).slice(5).replace('T', ' ')

// ---- Plan mode (`/api/plan`) ------------------------------------------------
// Mirrors src/watch_plan.py: prep_at = at - cold start; first-launch end is the
// query worst case (90 s) plus the configured submit margin; redemption uses
// the configured window. Plan scheduler values come from Settings → 其他.
const PLAN_PREP_MINUTES = SETTINGS.cold_start_minutes
const planEndMinutes = (mode: Mode) =>
  mode === 'redemption' ? SETTINGS.irregular_window_minutes : state.planSettings.first_end_slack_minutes + 1.5
const planArmGap = () => state.planSettings.arm_gap_minutes
const planClock = (value: string) => /T(\d{2}:\d{2})/.exec(value)?.[1] ?? value

function planItemView(item: PlanItem): PlanItem {
  const at = parseLocal(item.at)
  if (!at) return { ...item }
  const immediate = SETTINGS.cold_start_minutes === 0
  return {
    ...item,
    prep_at: immediate ? null : localISO(new Date(at.getTime() - PLAN_PREP_MINUTES * 60_000)),
    prep_mode: immediate ? 'immediate' : 'scheduled',
    prep_text: immediate ? '开始后立即准备' : null,
    end_at: localISO(new Date(at.getTime() + planEndMinutes(item.mode) * 60_000)),
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
    if (at.getTime() > now + 14 * 24 * 3600_000) return [`第 ${index + 1} 项购买时间超过 14 天。`]
    return []
  })
  for (let index = 1; index < items.length; index += 1) {
    const previous = items[index - 1]
    const current = items[index]
    const previousAt = parseLocal(previous.at)
    const currentAt = parseLocal(current.at)
    if (!previousAt || !currentAt) continue
    const previousEnd = previousAt.getTime() + planEndMinutes(previous.mode) * 60_000
    const currentPrep = currentAt.getTime() - PLAN_PREP_MINUTES * 60_000
    if (currentPrep >= previousEnd + planArmGap() * 60_000) continue
    const minimum = Math.ceil(
      (previousEnd - previousAt.getTime() + (PLAN_PREP_MINUTES + planArmGap()) * 60_000) / 60_000,
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
  if (Date.now() > prepAt - planArmGap() * 60_000 && at.getTime() > Date.now())
    return ['第一项已进入冷启动时间，开始后将立即冷启动。']
  return []
}

function planContentRevision(plan: Plan) {
  return `mock-content:${JSON.stringify({
    dry_run: plan.dry_run,
    items: plan.items.map(({ code, amount, at, mode }) => ({ code, amount, at, mode })),
  })}`
}

function planView(): PlanView {
  const plan = state.plan
  const running = plan?.phase === 'running'
  const heartbeatTimeout = state.planSettings.heartbeat_timeout_seconds
  const lastTick = plan?.last_tick ? parseLocal(plan.last_tick) : null
  const heartbeatAge = lastTick ? Math.max(0, Math.round((Date.now() - lastTick.getTime()) / 1000)) : null
  return {
    plan: plan
      ? { ...plan, content_revision: planContentRevision(plan), items: plan.items.map(planItemView) }
      : null,
    running,
    stale: false,
    heartbeat_stale: running && (heartbeatAge == null || heartbeatAge > heartbeatTimeout),
    heartbeat_age_s: heartbeatAge,
    heartbeat_timeout_s: heartbeatTimeout,
    settings_changed: false,
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
  http.get('/api/settings/other', () => HttpResponse.json({ settings: state.planSettings })),
  http.put('/api/settings/other', async ({ request }) => {
    Object.assign(state.planSettings, await request.json())
    return HttpResponse.json({ settings: state.planSettings })
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
  // Settings dialog: partial update, test item moved/cleared, quota_times replaced.
  http.put('/api/favorites/:code', async ({ request, params }) => {
    const body = (await request.json()) as FavoriteSettingsRequest
    const code = String(params.code)
    const row = state.favorites.find((favorite) => favorite.code.toLowerCase() === code.toLowerCase())
    if (!row) return fail('先收藏这个产品，再设置额度时间。')
    if (typeof body.title === 'string' && body.title.trim()) row.title = body.title.trim()
    if ('test_amount' in body) {
      const amount = (body.test_amount ?? '').trim()
      if (!amount) delete row.test_amount
      else {
        if (!validAmount(amount)) return fail('测试金额须为大于 0 的数字，最多两位小数。')
        for (const favorite of state.favorites) delete favorite.test_amount
        row.test_amount = amount
      }
    }
    if ('recent_annualized' in body) {
      const raw = (body.recent_annualized ?? '').trim()
      if (!raw) delete row.recent_annualized
      else row.recent_annualized = annualizedText(raw)
    }
    if ('quota_times' in body) {
      const entries = body.quota_times
      if (!Array.isArray(entries)) return fail('额度时间格式不正确。')
      if (entries.length > MAX_QUOTA_TIMES) return fail('额度时间最多 50 条。')
      const used = new Set<string>()
      const normalized = entries.map((entry) => normalizeQuotaTime(entry, used))
      if (normalized.length === 0) delete row.quota_times
      else row.quota_times = normalized
    }
    return HttpResponse.json({ favorites: state.favorites, ok: true })
  }),
  http.delete('/api/favorites/:code', ({ params }) => {
    state.favorites = state.favorites.filter((f) => f.code !== params.code)
    return HttpResponse.json({ favorites: state.favorites, ok: true })
  }),
  http.post('/api/credentials/:kind', () => HttpResponse.json({ ok: true })),
  // Push config: never echo the token; empty token keeps the saved one.
  http.get('/api/push', async () => {
    await delay(80)
    return HttpResponse.json(state.push)
  }),
  http.put('/api/push', async ({ request }) => {
    const body = (await request.json()) as { server?: string; topic?: string; token?: string }
    await delay(300)
    const server = (body.server ?? '').trim()
    const topic = (body.topic ?? '').trim()
    const token = (body.token ?? '').trim()
    if (!/^https:\/\/\S+$/i.test(server)) return fail('推送服务器地址必须是 https 地址。')
    if (!/^[-_A-Za-z0-9]{1,64}$/.test(topic))
      return fail('频道名只能包含字母、数字、- 和 _，最长 64 个字符。')
    if (!token && !state.push.configured) return fail('还没有保存的访问令牌，请填写后再保存。')
    state.push = {
      configured: true,
      server: server.endsWith('/') ? server : `${server}/`,
      topic,
      token_set: true,
    }
    return HttpResponse.json(state.push)
  }),
  http.post('/api/push/test', async () => {
    await delay(400)
    if (!state.push.configured) return fail('推送未配置。')
    // A server containing "fail" exercises the failure message in e2e.
    if (state.push.server?.includes('fail')) return HttpResponse.json({ sent: false, error: 'HTTP 401' })
    return HttpResponse.json({ sent: true })
  }),
  http.delete('/api/push', async () => {
    await delay(200)
    state.push = { configured: false, server: null, topic: null, token_set: false }
    return HttpResponse.json(state.push)
  }),
  http.get('/api/push/preferences', () => HttpResponse.json(state.pushPreferences)),
  http.put('/api/push/preferences', async ({ request }) => {
    const body = (await request.json()) as { enabled: boolean; events: Record<string, boolean> }
    if (typeof body.enabled !== 'boolean' || !body.events) return fail('通知偏好格式无效。')
    if (
      Object.entries(body.events).some(
        ([key, value]) => !(key in state.pushPreferences.events) || typeof value !== 'boolean',
      )
    )
      return fail('通知事件格式无效。')
    state.pushPreferences = {
      ...state.pushPreferences,
      enabled: body.enabled,
      events: { ...state.pushPreferences.events, ...body.events },
    }
    return HttpResponse.json(state.pushPreferences)
  }),
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
    const body = (await request.json().catch(() => ({}))) as {
      confirm_real_payment?: boolean
      plan_id?: string
      content_revision?: string
      settings_revision?: string
    }
    await delay(400)
    const plan = state.plan
    if (!plan) return fail('计划里还没有布防。')
    if (plan.phase === 'running') return fail('计划正在运行；先取消计划再开始。')
    if (plan.phase !== 'idle') return fail('计划已结束；请清空后重新保存再开始。')
    const problems = planProblems(plan)
    if (problems.length) return fail(problems[0])
    if (!plan.dry_run && !body.confirm_real_payment) return fail('真实计划必须明确确认实际付款。')
    if (
      body.plan_id !== plan.plan_id ||
      body.content_revision !== planContentRevision(plan) ||
      body.settings_revision !== 'mock-revision'
    )
      return fail('计划内容或值守配置已变化，或缺少确认版本；请重新读取计划并核对后开始。')
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
