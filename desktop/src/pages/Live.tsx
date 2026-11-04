import { useQuery } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { q, useAction, useWatch } from '../api/hooks'
import { Button } from '../components/ui/button'
import { Confirm } from '../components/ui/dialog'
import { clockTime, cn, parseLocal, phaseName, phaseTone, shortTime, toneBg } from '../lib/utils'
import { useUI } from '../store'

/**
 * Focus view shown in the content area while a watch task is active. The live log
 * drifts behind a floating panel; the newest line glows; the countdown ticks with
 * each digit sliding in.
 */
export function LivePage() {
  const w = useWatch()
  const busy = useUI((s) => s.busy)
  const lastRefresh = useUI((s) => s.lastRefresh)
  const action = useAction()
  const [confirmDisarm, setConfirmDisarm] = useState(false)
  const [now, setNow] = useState(() => new Date())
  const { data: log } = useQuery({ ...q.log(160), refetchInterval: 1500 })

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 250)
    return () => clearInterval(timer)
  }, [])

  const task = w.task ?? {}
  const redemption = task.mode === 'redemption'
  const target =
    redemption && (w.phase === 'waiting' || w.phase === 'firing')
      ? parseLocal(task.end_at)
      : (parseLocal(task.fire_at) ?? parseLocal(task.at))
  const countdown = (() => {
    if (w.phase === 'firing') return '00:00'
    if (!target) return '--:--'
    const total = Math.max(0, Math.floor((+target - +now) / 1000))
    const h = Math.floor(total / 3600)
    const m = String(Math.floor((total % 3600) / 60)).padStart(2, '0')
    const s = String(total % 60).padStart(2, '0')
    return h > 0 ? `${h}:${m}:${s}` : `${m}:${s}`
  })()
  const hint =
    w.phase === 'firing'
      ? '正在提交，请勿操作'
      : redemption
        ? w.phase === 'waiting'
          ? '距窗口结束'
          : '距开始查询'
        : '距开售'

  return (
    <motion.div
      data-testid="live"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.25 }}
      className="relative flex h-full flex-col overflow-hidden bg-bg"
    >
      <LogStream lines={log?.lines ?? []} first={(log?.total ?? 0) - (log?.lines.length ?? 0)} />
      <div className="relative z-10 flex flex-1 flex-col px-[30px] py-6">
        <div className="flex items-center gap-3">
          <span className="relative flex size-[7px]">
            <span
              className={cn(
                'absolute inset-0 animate-ping rounded-full opacity-60',
                toneBg[phaseTone(w.phase)],
              )}
            />
            <span className={cn('relative size-[7px] rounded-full', toneBg[phaseTone(w.phase)])} />
          </span>
          <span className="font-semibold text-[13px]">{phaseName(w.phase)}</span>
          <span className="rounded-full bg-[#383838] px-2 py-[3px] font-medium text-[10px] text-muted">
            {redemption ? '不定时抢购' : '首发模式'}
          </span>
          <span className="flex-1" />
          <span className="font-mono text-[10px] text-muted">
            上次刷新 {lastRefresh ? clockTime(lastRefresh) : '尚未刷新'}
          </span>
        </div>
        <div className="flex-1" />
        <motion.section
          initial={{ opacity: 0, y: 40, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ type: 'spring', stiffness: 220, damping: 24, delay: 0.05 }}
          className="mb-1.5 flex w-full max-w-[680px] flex-col gap-[18px] rounded-[20px] bg-[#1d1d1d]/90 p-[26px] ring-[0.6px] ring-[#575757]/65 backdrop-blur-md"
          style={{ boxShadow: '0 16px 60px rgb(0 0 0 / 0.55), 0 0 92px rgb(224 66 82 / 0.12)' }}
        >
          <div className="flex items-baseline gap-3.5">
            <Countdown text={countdown} />
            <span className="text-muted text-xs">{hint}</span>
          </div>
          <div className="h-[0.6px] bg-[#474747]" />
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

/** Each character slides up when it changes, like a split-flap counter. */
function Countdown({ text }: { text: string }) {
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
          <AnimatePresence mode="popLayout" initial={false}>
            <motion.span
              key={char}
              className="inline-block"
              initial={{ y: '60%', opacity: 0, filter: 'blur(4px)' }}
              animate={{ y: 0, opacity: 1, filter: 'blur(0px)' }}
              exit={{ y: '-60%', opacity: 0, filter: 'blur(4px)' }}
              transition={{ type: 'spring', stiffness: 380, damping: 30 }}
            >
              {char}
            </motion.span>
          </AnimatePresence>
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

/** Background log: newest line glows, new lines rise in, the whole stream drifts slowly. */
function LogStream({ lines, first }: { lines: string[]; first: number }) {
  const tail = useRef<HTMLDivElement>(null)
  const shown = lines.slice(-160)
  // Absolute line numbers as keys, so only genuinely new lines animate in.
  const offset = first + lines.length - shown.length
  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll whenever a new line arrives
  useEffect(() => {
    tail.current?.scrollIntoView({ block: 'end' })
  }, [shown.at(-1)])
  return (
    <motion.div
      aria-hidden
      animate={{ y: [0, -5, 0] }}
      transition={{ duration: 18, repeat: Number.POSITIVE_INFINITY, ease: 'easeInOut' }}
      className="pointer-events-none absolute inset-0 overflow-hidden opacity-60 [mask-image:linear-gradient(to_bottom,transparent,black_18%,black_72%,transparent)]"
    >
      <div className="flex h-full flex-col gap-[3px] overflow-y-hidden px-[30px] pt-[66px] pb-[250px]">
        <AnimatePresence initial={false}>
          {shown.map((line, index) => {
            const newest = index === shown.length - 1
            return (
              <motion.div
                // biome-ignore lint/suspicious/noArrayIndexKey: offset + index is the absolute line number
                key={offset + index}
                layout="position"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35 }}
                className={cn(
                  'truncate font-mono text-[11px] transition-colors duration-700',
                  newest ? 'text-[#d6d6d6] [filter:drop-shadow(0_0_5px_rgb(255_255_255/0.35))]' : 'text-[#808080]',
                )}
              >
                {line}
              </motion.div>
            )
          })}
        </AnimatePresence>
        <div ref={tail} className="h-px shrink-0" />
      </div>
    </motion.div>
  )
}
