import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { Fragment, memo } from 'react'
import { type Progress, STEPS, type StepState } from '../lib/progress'
import { cn } from '../lib/utils'

/**
 * The purchase chain (P1–P12, execution order) drawn into the focus view's
 * backdrop, like the scrolling code: a bare rail under the task card, no panel.
 * It never takes layout space and ignores the pointer. Done nodes dim, the
 * running one glows and types its real call chain underneath.
 */
export const ChainProgress = memo(function ChainProgress({
  progress,
  active = true,
}: {
  progress: Progress
  active?: boolean
}) {
  const done = progress.states.filter((s) => s === 'done').length
  const total = STEPS.length - (progress.dryRun ? 1 : 0)
  const current = progress.active >= 0 ? progress.active : null
  return (
    <section
      data-testid="chain-progress"
      data-active={active ? 'true' : 'false'}
      aria-label={`购买链路进度 ${done}/${total}`}
      className="pointer-events-none absolute inset-x-[30px] bottom-[5%] z-[5] flex flex-col gap-2.5 font-mono [text-shadow:0_1px_8px_rgb(0_0_0/0.9)]"
    >
      <div className="flex items-center gap-2 text-[10px] text-white/30">
        <span className="text-accent/70">▸</span>
        <span>purchase_chain</span>
        <span className="tabular-nums">
          <span className="text-white/70">{done}</span>/{total}
        </span>
      </div>
      <ol className="flex items-center">
        {STEPS.map((step, i) => (
          <Fragment key={step.id}>
            {i > 0 && (
              <Link
                from={progress.states[i - 1]}
                fired={!!step.fired && !STEPS[i - 1].fired}
                active={active}
              />
            )}
            <Node id={step.id} state={progress.states[i]} running={i === current} active={active} />
          </Fragment>
        ))}
      </ol>
      <Detail progress={progress} current={current} active={active} />
    </section>
  )
})

function Node({
  id,
  state,
  running,
  active,
}: {
  id: string
  state: StepState
  running: boolean
  active: boolean
}) {
  return (
    <li aria-current={running ? 'step' : undefined} className="relative flex shrink-0 flex-col items-center">
      <span className="relative flex size-3 items-center justify-center">
        {running && active && (
          <span className="absolute inset-[-3px] animate-ping rounded-full bg-accent/40" />
        )}
        <span
          className={cn(
            'relative rounded-full',
            active && 'transition-all duration-500',
            running && 'size-2.5 bg-accent shadow-[0_0_12px_rgb(224_66_82/0.95)]',
            !running && state === 'done' && 'size-[7px] bg-accent/60',
            state === 'failed' && 'size-2.5 bg-accent ring-2 ring-accent/30',
            state === 'pending' && 'size-[7px] border border-white/20',
            state === 'skipped' && 'size-[7px] border border-white/20 border-dashed',
          )}
        />
      </span>
      <span
        className={cn(
          'absolute top-[17px] text-[10px] tabular-nums',
          active && 'transition-colors duration-500',
          running || state === 'failed'
            ? 'text-accent'
            : state === 'done'
              ? 'text-white/40'
              : 'text-white/20',
        )}
      >
        {id}
      </span>
    </li>
  )
}

/** Connector between two nodes; the one crossing fired_at is dashed red. */
function Link({ from, fired, active }: { from: StepState; fired: boolean; active: boolean }) {
  const lit = from === 'done'
  if (fired)
    return (
      <li aria-hidden className="relative h-px min-w-3 flex-1 border-t border-dashed border-accent/60">
        <span className="-translate-x-1/2 absolute bottom-[5px] left-1/2 whitespace-nowrap text-[10px] text-accent/70">
          fired_at
        </span>
      </li>
    )
  return (
    <li
      aria-hidden
      className={cn(
        'h-px min-w-3 flex-1',
        active && 'transition-colors duration-500',
        lit ? 'bg-accent/45' : 'bg-white/10',
      )}
    />
  )
}

/** One line under the rail: the running step and its call chain, or a summary. */
function Detail({
  progress,
  current,
  active,
}: {
  progress: Progress
  current: number | null
  active: boolean
}) {
  const reduce = useReducedMotion()
  const step = current !== null ? STEPS[current] : null
  return (
    <div className="mt-[22px] flex h-[30px] flex-col gap-[3px] text-[10px]">
      <AnimatePresence mode="wait" initial={false}>
        {step ? (
          <motion.div
            key={step.id}
            initial={active ? { opacity: 0, y: 4 } : false}
            animate={{ opacity: 1, y: 0 }}
            exit={active ? { opacity: 0 } : undefined}
            transition={{ duration: active ? 0.25 : 0 }}
            className="flex min-w-0 items-baseline gap-2"
          >
            <span className="text-accent">{step.id}</span>
            <span className="shrink-0 font-sans text-white/85 text-xs">{step.name}</span>
            <motion.span
              initial={reduce || !active ? false : { clipPath: 'inset(0 100% 0 0)' }}
              animate={{ clipPath: 'inset(0 0% 0 0)' }}
              transition={{ duration: active ? 0.9 : 0, ease: 'linear' }}
              className="truncate text-white/55"
            >
              {step.chain}
            </motion.span>
            <span className={cn('text-accent', active && 'animate-pulse')}>▍</span>
          </motion.div>
        ) : (
          <motion.div
            key="summary"
            initial={active ? { opacity: 0 } : false}
            animate={{ opacity: 1 }}
            className="truncate text-white/45"
          >
            {summary(progress)}
          </motion.div>
        )}
      </AnimatePresence>
      {step?.id === 'P7' && progress.queries.length > 0 && (
        <span className="truncate text-white/35 tabular-nums">
          {progress.queries
            .slice(-5)
            .map((q) => `#${q.attempt} ${q.outcome} ${q.ms}ms`)
            .join('  ·  ')}
          {'  '}共 {progress.queries.length} 次
        </span>
      )}
    </div>
  )
}

function summary(progress: Progress) {
  const failed = progress.states.indexOf('failed')
  if (failed >= 0) return `${STEPS[failed].id} ${STEPS[failed].name} 停止`
  const parts = (['P9', 'P10', 'P11', 'P12'] as const)
    .filter((id) => progress.offsets[id] !== undefined)
    .map((id) => `${STEPS.find((s) => s.id === id)?.name} +${progress.offsets[id]}ms`)
  if (parts.length) return `完成 · 从有额度起 ${parts.join(' · ')}`
  return ''
}
