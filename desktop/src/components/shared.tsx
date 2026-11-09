import * as Menu from '@radix-ui/react-dropdown-menu'
import { useQuery } from '@tanstack/react-query'
import { LoaderCircle, Star } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { q, useAction, useWatch } from '../api/hooks'
import type { Favorite } from '../api/types'
import { cn, copyText, formatAmount } from '../lib/utils'
import { useUI } from '../store'
import { Button } from './ui/button'
import { Hint } from './ui/card'
import { Dialog } from './ui/dialog'

export function Spinner({ className }: { className?: string }) {
  return <LoaderCircle className={cn('size-3.5 animate-spin text-muted', className)} />
}

export function LogText({ lines, className }: { lines: string[]; className?: string }) {
  return (
    <pre
      className={cn(
        'selectable min-h-0 overflow-auto whitespace-pre font-mono text-[#b8b8b8] text-[10px] leading-[1.6]',
        className,
      )}
    >
      {lines.length ? lines.join('\n') : '暂无日志'}
    </pre>
  )
}

/**
 * Inline log preview with no scrollbar: the newest `maxLines` lines, one
 * truncated row each. Full logs are only read in LogDialog (2026-11-06
 * requirement: areas like 最近日志 / 值守日志 must not scroll).
 */
export function LogPreview({
  lines,
  maxLines = 8,
  align = 'top',
  fitLines = false,
  testId,
  className,
}: {
  lines: string[]
  maxLines?: number
  /** bottom keeps the newest line against the bottom edge, like a terminal. */
  align?: 'top' | 'bottom'
  /** measure the box and show only whole lines that fit (flex-sized previews). */
  fitLines?: boolean
  testId?: string
  className?: string
}) {
  const box = useRef<HTMLDivElement>(null)
  const [fit, setFit] = useState(maxLines)
  useEffect(() => {
    const el = box.current
    if (!el || !fitLines) return
    const measure = () => {
      const style = getComputedStyle(el)
      const lineHeight = Number.parseFloat(style.lineHeight) || 16
      const padding = Number.parseFloat(style.paddingTop) + Number.parseFloat(style.paddingBottom)
      setFit(Math.max(1, Math.min(maxLines, Math.floor((el.clientHeight - padding) / lineHeight))))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [fitLines, maxLines])
  const limit = fitLines ? fit : maxLines
  const shown = lines.slice(-limit)
  const first = lines.length - shown.length
  return (
    <div
      ref={box}
      data-testid={testId}
      className={cn(
        'flex min-h-0 min-w-0 flex-col overflow-hidden font-mono text-[#b8b8b8] text-[10px] leading-[1.6]',
        align === 'bottom' && 'justify-end',
        className,
      )}
    >
      {shown.length ? (
        shown.map((line, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: offset + index is the absolute line number
          <div key={first + index} title={line} className="min-w-0 shrink-0 truncate">
            {line || ' '}
          </div>
        ))
      ) : (
        <span className="text-muted">暂无日志</span>
      )}
    </div>
  )
}

export function BusyLine({ text }: { text?: string | null }) {
  const label = useUI((s) => s.busyLabel)
  return (
    <div className="flex items-center gap-2">
      <Spinner className="text-accent" />
      <span className="text-[11px] text-accent">{text ?? (label || '处理中…')}</span>
    </div>
  )
}

/** Small purple tag for the one favorite that is the drill test item. */
export function TestTag({ amount, testId }: { amount: string; testId?: string }) {
  return (
    <span
      data-testid={testId}
      className="whitespace-nowrap rounded bg-purple/15 px-1.5 py-[1px] font-medium text-[9px] text-purple leading-none"
    >
      测试 ¥{formatAmount(amount)}
    </span>
  )
}

/** Green tag under a favourite's code: successful submissions found in history. */
export function SuccessTag({ count, testId }: { count: number; testId?: string }) {
  return (
    <span
      data-testid={testId}
      title={`历史成功提交 ${count} 单`}
      className="whitespace-nowrap rounded bg-good/15 px-1.5 py-[1px] font-medium text-[9px] text-good leading-none"
    >
      {count} 单
    </span>
  )
}

/** Compact chips that fill product code (and test amount) from saved favorites. */
export function FavoritePicker({ onPick }: { onPick: (row: Favorite) => void }) {
  const { favorites } = useWatch()
  if (!favorites.length) return null
  const label = (row: Favorite) => row.title || row.code
  // Keep the test item among the visible chips even with more than four.
  const ordered = [...favorites].sort(
    (a, b) => Number(Boolean(b.test_amount)) - Number(Boolean(a.test_amount)),
  )
  return (
    <div className="flex flex-wrap items-center gap-[7px]">
      <Star className="size-2.5 fill-warn/85 text-warn/85" />
      {ordered.slice(0, 4).map((row) => (
        <Button
          key={row.code}
          size="compact"
          data-testid={`favorite-${row.code}`}
          onClick={() => onPick(row)}
        >
          {label(row)}
          {row.test_amount && <TestTag amount={row.test_amount} />}
        </Button>
      ))}
      {favorites.length > 4 && (
        <Menu.Root>
          <Menu.Trigger asChild>
            <Button size="compact" variant="ghost">
              更多
            </Button>
          </Menu.Trigger>
          <Menu.Portal>
            <Menu.Content
              sideOffset={4}
              className="z-[70] min-w-[180px] rounded-lg bg-button p-1 shadow-xl ring-1 ring-white/8"
            >
              {ordered.map((row) => (
                <Menu.Item
                  key={row.code}
                  onSelect={() => onPick(row)}
                  className="cursor-pointer rounded-md px-2.5 py-1.5 text-xs outline-none data-[highlighted]:bg-accent"
                >
                  {label(row)} · {row.code}
                  {row.test_amount ? ` · 测试 ¥${formatAmount(row.test_amount)}` : ''}
                </Menu.Item>
              ))}
            </Menu.Content>
          </Menu.Portal>
        </Menu.Root>
      )}
    </div>
  )
}

/** Full watch.log with copy / open-file. Loads 1200 lines when opened. */
export function LogDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const action = useAction()
  const { data } = useQuery({ ...q.log(1200), enabled: open })
  const lines = data?.lines ?? []
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="值守日志"
      width={860}
      height={580}
      actions={
        <>
          <Button onClick={() => copyText(lines.join('\n'))}>复制</Button>
          <Button onClick={() => action('打开日志', () => api('POST', '/api/open-log'), false)}>
            打开文件
          </Button>
        </>
      }
    >
      <LogText lines={lines} className="flex-1" />
      <Hint className="text-[10px]">日志为全局 watch.log，不按任务拆分。</Hint>
    </Dialog>
  )
}
