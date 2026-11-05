import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn, type Tone, toneBg, toneText } from '../../lib/utils'

export function Card({
  title,
  subtitle,
  badge,
  children,
  className,
}: {
  title: string
  subtitle?: string
  /** Right-aligned mark in the title row; says how the card's numbers behave. */
  badge?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={cn('flex flex-col gap-4 rounded-[14px] bg-card p-[18px]', className)}>
      <header className="flex flex-col gap-[5px]">
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-semibold text-sm">{title}</h2>
          {badge}
        </div>
        {subtitle && <p className="text-muted text-xs">{subtitle}</p>}
      </header>
      {children}
    </section>
  )
}

/** Status-page card: scrolling body, footer pinned to the bottom. */
export function DashboardCard({
  title,
  icon: Icon,
  children,
  footer,
  testId,
}: {
  title: string
  icon: LucideIcon
  children: ReactNode
  footer: ReactNode
  testId?: string
}) {
  return (
    <section data-testid={testId} className="flex min-h-0 flex-col gap-[9px] rounded-[14px] bg-card p-3">
      <header className="flex items-center gap-2">
        <Icon className="size-3 text-muted" strokeWidth={2.5} />
        <h2 className="font-semibold text-[13px]">{title}</h2>
      </header>
      <div className="flex min-h-0 flex-1 flex-col gap-[9px] overflow-y-auto">{children}</div>
      <footer className="flex items-center gap-2">{footer}</footer>
    </section>
  )
}

export function IconTile({ icon: Icon, tone }: { icon: LucideIcon; tone: Tone }) {
  return (
    <div
      className={cn(
        'relative flex size-10 shrink-0 items-center justify-center rounded-[10px]',
        toneText[tone],
      )}
    >
      <div className={cn('absolute inset-0 rounded-[10px] opacity-15', toneBg[tone])} />
      <Icon className="relative size-[18px]" strokeWidth={2.4} />
    </div>
  )
}

export function Badge({ children, tone = 'muted' }: { children: ReactNode; tone?: Tone }) {
  return (
    <span
      className={cn(
        'relative inline-flex shrink-0 items-center rounded-full px-2 py-[3px] font-semibold text-[10px]',
        toneText[tone],
      )}
    >
      <span className={cn('absolute inset-0 rounded-full opacity-15', toneBg[tone])} />
      <span className="relative">{children}</span>
    </span>
  )
}

export function Metric({ title, value, tone }: { title: string; value: string; tone?: Tone }) {
  return (
    <div className="flex min-w-0 flex-col gap-[3px]">
      <span className="truncate text-[10px] text-muted">{title}</span>
      <span className={cn('truncate font-medium text-xs', tone ? toneText[tone] : 'text-[#ebebeb]')}>
        {value}
      </span>
    </div>
  )
}

export function MetricGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-x-3 gap-y-2">{children}</div>
}

export function Detail({ title, value }: { title: string; value: unknown }) {
  const text = typeof value === 'string' || typeof value === 'number' ? String(value) : '—'
  return (
    <div className="flex min-w-0 flex-col gap-[7px]">
      <span className="text-[11px] text-muted">{title}</span>
      <span className="selectable break-words font-medium text-[13px]">{text}</span>
    </div>
  )
}

export function StatusDot({ state }: { state: boolean | null }) {
  return (
    <span
      className={cn('size-1.5 rounded-full', state === null ? 'bg-muted' : state ? 'bg-good' : 'bg-warn')}
    />
  )
}

export function Hint({
  children,
  tone = 'muted',
  className,
}: {
  children: ReactNode
  tone?: Tone
  className?: string
}) {
  return <p className={cn('text-[11px] leading-snug', toneText[tone], className)}>{children}</p>
}
