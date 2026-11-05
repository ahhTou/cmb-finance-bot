import { delay, HttpResponse, http } from 'msw'
import type { ArmRequest, CancelRequest, Favorite, Task } from '../api/types'
import { localISO } from '../lib/utils'
import {
  DEVICE,
  DRILL_SCRIPT,
  FAVORITES,
  HISTORY,
  LOG_LINES,
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
}
const active = () => ['armed', 'preparing', 'waiting', 'firing'].includes(state.task?.phase ?? '')
const fail = (error: string, status = 400) => HttpResponse.json({ error }, { status })
const status = () => makeStatus(state.task, state.favorites, state.logs)

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
]
