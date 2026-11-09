import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { memo, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import { q, useAction, useWatch } from '../api/hooks'
import { ChainProgress } from '../components/ChainProgress'
import { Button } from '../components/ui/button'
import { Confirm } from '../components/ui/dialog'
import { useWindowActive } from '../lib/focus'
import { readProgress } from '../lib/progress'
import { clockTime, cn, parseLocal, phaseName, phaseTone, shortTime, toneBg } from '../lib/utils'
import { useUI } from '../store'

/** Countdown to the sale (or to the end of the redemption window), ticking four times a second. */
export function useCountdown() {
  const w = useWatch()
  const active = useWindowActive()
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    // Refocusing refreshes the countdown at once; in the background a minute is
    // plenty (nobody is looking) and one tick per minute costs no measurable CPU.
    setNow(Date.now())
    const timer = setInterval(() => setNow(Date.now()), active ? 250 : 60_000)
    return () => clearInterval(timer)
  }, [active])
  const task = w.task ?? {}
  const redemption = task.mode === 'redemption'
  const target =
    redemption && (w.phase === 'waiting' || w.phase === 'firing')
      ? parseLocal(task.end_at)
      : (parseLocal(task.fire_at) ?? parseLocal(task.at))
  let text = '--:--'
  if (w.phase === 'firing') text = '00:00'
  else if (target) {
    const total = Math.max(0, Math.floor((+target - now) / 1000))
    const h = Math.floor(total / 3600)
    const m = String(Math.floor((total % 3600) / 60)).padStart(2, '0')
    const s = String(total % 60).padStart(2, '0')
    text = h > 0 ? `${h}:${m}:${s}` : `${m}:${s}`
  }
  const hint =
    w.phase === 'firing'
      ? '正在提交，请勿操作'
      : redemption
        ? w.phase === 'waiting'
          ? '距窗口结束'
          : '距开始查询'
        : '距开售'
  return { w, task, redemption, text, hint }
}

/** Solid panel over the animated background. */
const panel = (boxShadow: string) => ({ boxShadow, background: '#191919' })

function PhaseDot({ phase, active = true, size = 7 }: { phase: string; active?: boolean; size?: number }) {
  return (
    <span
      data-testid="phase-dot"
      data-active={active ? 'true' : 'false'}
      className="relative flex shrink-0"
      style={{ width: size, height: size }}
    >
      <span
        className={cn(
          'absolute inset-0 rounded-full opacity-60',
          active && 'animate-ping',
          toneBg[phaseTone(phase)],
        )}
      />
      <span className={cn('relative size-full rounded-full', toneBg[phaseTone(phase)])} />
    </span>
  )
}

/**
 * Focus view on the Tasks page while a watch task is active: the task card floats
 * in the middle over the live log, scrolling project code and glowing waves.
 */
export function LivePage() {
  // The countdown ticks four times a second; keep that re-render inside
  // <CountdownLine> so the log stream and chain rail only render on new data.
  const w = useWatch()
  const active = useWindowActive()
  const task = w.task ?? {}
  const redemption = task.mode === 'redemption'
  const busy = useUI((s) => s.busy)
  const lastRefresh = useUI((s) => s.lastRefresh)
  const action = useAction()
  const [confirmDisarm, setConfirmDisarm] = useState(false)
  // Enough lines to reach back to this task's start (P7 logs one line per
  // query); poll faster once queries run, when steps pass in a second.
  const hot = w.phase === 'waiting' || w.phase === 'firing'
  const { data: log } = useQuery({ ...q.log(400), refetchInterval: hot ? 700 : 1500 })
  const lines = useMemo(() => log?.lines ?? [], [log])
  const progress = useMemo(() => readProgress(lines, w.phase, !!task.dry_run), [lines, w.phase, task.dry_run])

  return (
    <motion.div
      data-testid="live"
      data-window-active={active ? 'true' : 'false'}
      initial={active ? { opacity: 0 } : false}
      animate={{ opacity: 1 }}
      transition={{ duration: active ? 0.3 : 0 }}
      className="relative flex h-full flex-col overflow-hidden bg-bg"
    >
      <CodeRain active={active} />
      <Waves phase={w.phase} active={active} />
      <LogStream lines={lines} first={(log?.total ?? 0) - lines.length} active={active} />
      {/* The whole top band drags the window; the bar under it only shows text. */}
      <div data-tauri-drag-region className="absolute inset-x-0 top-0 z-20 h-[72px]" />
      <div className="pointer-events-none relative z-10 flex items-center gap-3 px-[30px] pt-6">
        <PhaseDot phase={w.phase} active={active} />
        <span className="font-semibold text-[13px]">{phaseName(w.phase)}</span>
        <span className="rounded-full bg-[#383838]/80 px-2 py-[3px] font-medium text-[10px] text-muted">
          {redemption ? '不定时抢购' : '首发模式'}
        </span>
        {task.dry_run && (
          <span className="rounded-full bg-[#383838]/80 px-2 py-[3px] font-medium text-[10px] text-muted">
            演练
          </span>
        )}
        <span className="flex-1" />
        <span className="font-mono text-[10px] text-muted">
          上次刷新 {lastRefresh ? clockTime(lastRefresh) : '尚未刷新'}
        </span>
      </div>
      <ChainProgress progress={progress} active={active} />
      <div className="relative z-10 flex flex-1 items-center justify-center px-[30px] pb-6">
        <motion.section
          initial={active ? { opacity: 0, y: 16 } : false}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: active ? 0.4 : 0, ease: [0.2, 0.8, 0.2, 1] }}
          className="flex w-full max-w-[680px] flex-col gap-[18px] rounded-[20px] p-[26px] ring-[0.6px] ring-white/15"
          style={panel(
            '0 30px 90px rgb(0 0 0 / 0.8), 0 10px 28px rgb(0 0 0 / 0.55), 0 0 120px rgb(224 66 82 / 0.2)',
          )}
        >
          <CountdownLine active={active} />
          <div className="h-[0.6px] bg-white/15" />
          <div className="flex items-end gap-[34px]">
            <Stat title="产品" value={task.code ?? '—'} />
            <Stat title="金额" value={`${task.amount ?? '—'} 元`} />
            <Stat title="计划" value={shortTime(task.at)} />
            {redemption ? (
              <Stat title="窗口" value={`${task.window_minutes ?? '—'} 分钟`} />
            ) : (
              <Stat title="提前量" value={`${task.prep_minutes ?? '—'} 分钟`} />
            )}
            <span className="flex-1" />
            <Button
              variant="primary"
              disabled={busy || w.phase === 'firing'}
              onClick={() => setConfirmDisarm(true)}
            >
              终止布防
            </Button>
          </div>
        </motion.section>
      </div>
      <Confirm
        open={confirmDisarm}
        onOpenChange={setConfirmDisarm}
        title="终止本轮布防？"
        message="终止后不会再提交；已经发生的交易仍要查交易记录。"
        cancel="继续值守"
        confirm="确认终止"
        onConfirm={() => action('终止布防', () => api('POST', '/api/disarm'))}
      />
    </motion.div>
  )
}

/** Running task at the bottom of the sidebar, shown on other pages; a click goes back to the focus view. */
export function WatchBubble() {
  const navigate = useNavigate()
  const active = useWindowActive()
  const { w, task, text, hint } = useCountdown()
  return (
    <motion.button
      type="button"
      data-testid="watch-bubble"
      aria-label={`${phaseName(w.phase)} ${task.code ?? ''}，${hint} ${text}，回到值守页`}
      initial={active ? { opacity: 0, y: 6 } : false}
      animate={{ opacity: 1, y: 0 }}
      exit={active ? { opacity: 0, y: 6 } : undefined}
      transition={{ duration: active ? 0.18 : 0 }}
      onClick={() => navigate({ to: '/tasks' })}
      className="flex w-full flex-col gap-1.5 rounded-xl p-3 text-left ring-[0.6px] ring-white/12 transition-colors hover:ring-accent/50"
      style={panel(
        '0 14px 36px rgb(0 0 0 / 0.65), 0 4px 12px rgb(0 0 0 / 0.45), 0 0 40px rgb(224 66 82 / 0.2)',
      )}
    >
      <span className="flex items-center gap-2 text-[11px] text-muted">
        <PhaseDot phase={w.phase} active={active} />
        <span className="truncate">
          {phaseName(w.phase)} · {task.code ?? '—'}
        </span>
      </span>
      <span className="font-rounded font-semibold text-[22px] tabular-nums leading-none">{text}</span>
      <span className="text-[10px] text-muted">{hint}</span>
    </motion.button>
  )
}

function CountdownLine({ active }: { active: boolean }) {
  const { text, hint } = useCountdown()
  return (
    <div className="flex items-baseline gap-3.5">
      <Countdown text={text} active={active} />
      <span className="text-muted text-xs">{hint}</span>
    </div>
  )
}

/**
 * Each character slides up when it changes, like a split-flap counter. While the
 * window is in the background the digits are plain text: no AnimatePresence, no
 * spring, and the countdown only updates once a minute.
 */
function Countdown({ text, active }: { text: string; active: boolean }) {
  return (
    <span
      data-testid="countdown"
      role="timer"
      aria-label={text}
      className="flex font-rounded font-semibold text-[58px] tabular-nums leading-none"
    >
      {text.split('').map((char, index) => (
        <span
          // biome-ignore lint/suspicious/noArrayIndexKey: position is the identity of a digit slot
          key={`${text.length}-${index}`}
          className="relative inline-block overflow-hidden"
        >
          {active ? (
            <AnimatePresence mode="popLayout" initial={false}>
              <motion.span
                key={char}
                className="inline-block"
                initial={{ y: '60%', opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                exit={{ y: '-60%', opacity: 0 }}
                transition={{ type: 'spring', stiffness: 380, damping: 30 }}
              >
                {char}
              </motion.span>
            </AnimatePresence>
          ) : (
            <span className="inline-block">{char}</span>
          )}
        </span>
      ))}
    </span>
  )
}

function Stat({ title, value }: { title: string; value: string }) {
  return (
    <div className="flex flex-col gap-[5px]">
      <span className="text-[10px] text-muted">{title}</span>
      <span className="font-medium font-rounded text-lg tabular-nums">{value}</span>
    </div>
  )
}

/**
 * Real watch.log, newest at the bottom. Lines are stacked from the bottom up
 * (no scrolling), the newest glows, and new lines rise in.
 */
const LogStream = memo(function LogStream({
  lines,
  first,
  active,
}: {
  lines: string[]
  first: number
  active: boolean
}) {
  const shown = lines.slice(-36)
  const offset = first + lines.length - shown.length
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute top-[64px] right-[34%] bottom-[30%] left-[30px] flex flex-col justify-end overflow-hidden [mask-image:linear-gradient(to_bottom,transparent,black_35%)]"
    >
      <AnimatePresence initial={false}>
        {shown.map((line, index) => {
          const newest = index === shown.length - 1
          return (
            <motion.div
              // biome-ignore lint/suspicious/noArrayIndexKey: offset + index is the absolute line number
              key={offset + index}
              initial={active ? { opacity: 0, y: 10 } : false}
              animate={{ opacity: 1, y: 0 }}
              exit={active ? { opacity: 0 } : undefined}
              transition={{ duration: active ? 0.35 : 0 }}
              className={cn(
                'shrink-0 truncate py-[1.5px] font-mono text-[11px] transition-colors duration-700',
                newest ? 'text-[#e6e6e6]' : 'text-[#7a7a7a]',
              )}
            >
              {line}
            </motion.div>
          )
        })}
      </AnimatePresence>
    </div>
  )
})

// What the watcher is actually doing, as a faint backdrop.
const CODE = `async function gate(queryBuy) {
  const original = window.queryBuy
  window.queryBuy = (...args) => pending.push(args)
  await until(fireAt - advanceMs)
  for (let i = 0; i <= maxRetries; i++) {
    const quota = await original(...pending.shift())
    if (quota.available) return submitOnce(quota)
    await sleep(jitter(retryMin, retryMax))
  }
}
def run(task):
    task.phase = "preparing"
    cold_start(prep_minutes)
    login(pattern_from_keychain())
    open_purchase_page(task.code)
    wait_until(task.fire_at)
    task.phase = "firing"   # written before submit
    return submit_once(task.amount)
const keys = await padReady({ stable: 238 })
for (const digit of pin) await tap(keys[digit], gap(digit))
confirm.click()  // 只提交一次
adb shell settings put global stay_on_while_plugged_in 15
uia2.dump_hierarchy() -> 0.11s
cdp.evaluate("location.href").includes(code)
assert parse_amount("￥5,000.00") == 5000
heartbeat(interval=30, session="agent:watch")`.split('\n')

function CodeColumn({
  lines,
  duration,
  className,
  active,
}: {
  lines: string[]
  duration: number
  className: string
  active: boolean
}) {
  const reduce = useReducedMotion()
  return (
    <div className={cn('absolute top-0 bottom-0 overflow-hidden', className)}>
      <div
        className="flex flex-col gap-[5px] font-mono text-[10px] text-white/[0.075] leading-[1.5]"
        // Pausing keeps the current offset, so no layout or visual jump on blur.
        style={
          reduce
            ? undefined
            : {
                animation: `code-scroll ${duration}s linear infinite`,
                animationPlayState: active ? 'running' : 'paused',
              }
        }
      >
        {[...lines, ...lines].map((line, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: static duplicated text
          <span key={index} className="whitespace-pre">
            {line || ' '}
          </span>
        ))}
      </div>
    </div>
  )
}

function CodeRain({ active }: { active: boolean }) {
  return (
    <div
      aria-hidden
      data-testid="code-rain"
      data-active={active ? 'true' : 'false'}
      className="pointer-events-none absolute inset-0 [mask-image:linear-gradient(to_bottom,transparent,black_20%,black_70%,transparent)]"
    >
      <CodeColumn lines={CODE} duration={70} className="right-[4%] w-[30%]" active={active} />
      <CodeColumn
        lines={[...CODE.slice(9), ...CODE.slice(0, 9)]}
        duration={110}
        className="right-[36%] w-[30%] opacity-60"
        active={active}
      />
    </div>
  )
}

const WAVES = [
  { amp: 26, freq: 0.0062, speed: 0.55, y: 0.72, color: '224,66,82', alpha: 0.55, width: 1.6, blur: 14 },
  { amp: 34, freq: 0.0041, speed: 0.38, y: 0.76, color: '255,128,150', alpha: 0.28, width: 1.2, blur: 10 },
  { amp: 20, freq: 0.0085, speed: 0.7, y: 0.8, color: '184,115,242', alpha: 0.26, width: 1.1, blur: 10 },
  { amp: 42, freq: 0.0029, speed: 0.25, y: 0.84, color: '255,255,255', alpha: 0.1, width: 1, blur: 0 },
]

/** Layered glowing sine waves on a canvas; faster as the task gets closer to submitting. */
function Waves({ phase, active }: { phase: string; active: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const reduce = useReducedMotion()
  const speed = useRef(1)
  speed.current = phase === 'firing' ? 2.6 : phase === 'waiting' ? 1.35 : 1

  useEffect(() => {
    const el = canvas.current
    const ctx = el?.getContext('2d')
    // Nothing draws in the background: no frame loop is scheduled. The cleanup
    // cancels the pending frame, and the effect reruns (resizing first) on refocus.
    if (!el || !ctx || !active) return
    let width = 0
    let height = 0
    const resize = () => {
      // Soft glowing lines don't need Retina pixels; 1x quarters the fill cost.
      const dpr = 1
      width = el.clientWidth
      height = el.clientHeight
      el.width = width * dpr
      el.height = height * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(el)

    let t = 0
    let last = performance.now()
    let frame = 0
    const draw = (now: number) => {
      // ~30 fps is plenty for slow waves and halves the work on the WebKit GPU process.
      if (now - last < 32) {
        frame = requestAnimationFrame(draw)
        return
      }
      t += ((now - last) / 1000) * speed.current
      last = now
      ctx.clearRect(0, 0, width, height)
      ctx.globalCompositeOperation = 'lighter'
      WAVES.forEach((wave, i) => {
        const swell = 0.65 + 0.35 * Math.sin(t * 0.4 + i * 1.7)
        const base = height * wave.y
        ctx.beginPath()
        for (let x = 0; x <= width + 4; x += 4) {
          const y =
            base +
            Math.sin(x * wave.freq + t * wave.speed * 2 + i) * wave.amp * swell +
            Math.sin(x * wave.freq * 2.3 - t * wave.speed * 1.4) * wave.amp * 0.28
          if (x === 0) ctx.moveTo(x, y)
          else ctx.lineTo(x, y)
        }
        // Glow without shadowBlur (WebKit blurs canvas shadows on every frame):
        // a wide faint stroke under the thin one.
        if (wave.blur) {
          ctx.strokeStyle = `rgba(${wave.color},${wave.alpha * 0.18})`
          ctx.lineWidth = wave.width + wave.blur * 0.6
          ctx.stroke()
        }
        ctx.strokeStyle = `rgba(${wave.color},${wave.alpha})`
        ctx.lineWidth = wave.width
        ctx.stroke()
        if (i === 0) {
          // A faint glow under the leading wave.
          ctx.lineTo(width, height)
          ctx.lineTo(0, height)
          ctx.closePath()
          const fill = ctx.createLinearGradient(0, base - wave.amp, 0, height)
          fill.addColorStop(0, `rgba(${wave.color},0.10)`)
          fill.addColorStop(1, `rgba(${wave.color},0)`)
          ctx.fillStyle = fill
          ctx.fill()
        }
      })
      if (!reduce) frame = requestAnimationFrame(draw)
    }
    frame = requestAnimationFrame(draw)
    const onVisibility = () => {
      cancelAnimationFrame(frame)
      if (!document.hidden && !reduce) {
        last = performance.now()
        frame = requestAnimationFrame(draw)
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [reduce, active])

  return (
    <canvas
      ref={canvas}
      aria-hidden
      data-testid="waves"
      data-active={active ? 'true' : 'false'}
      className="pointer-events-none absolute inset-0 size-full"
    />
  )
}
