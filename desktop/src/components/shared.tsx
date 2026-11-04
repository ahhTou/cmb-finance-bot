import * as Menu from '@radix-ui/react-dropdown-menu'
import { useQuery } from '@tanstack/react-query'
import { LoaderCircle, Star } from 'lucide-react'
import { api } from '../api/client'
import { q, useAction, useWatch } from '../api/hooks'
import type { Favorite } from '../api/types'
import { cn, copyText } from '../lib/utils'
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

export function BusyLine({ text }: { text?: string | null }) {
  const label = useUI((s) => s.busyLabel)
  return (
    <div className="flex items-center gap-2">
      <Spinner className="text-accent" />
      <span className="text-[11px] text-accent">{text ?? (label || '处理中…')}</span>
    </div>
  )
}

/** Compact chips that fill a product-code field from saved favorites. */
export function FavoritePicker({ onPick }: { onPick: (code: string) => void }) {
  const { favorites } = useWatch()
  if (!favorites.length) return null
  const label = (row: Favorite) => row.title || row.code
  return (
    <div className="flex flex-wrap items-center gap-[7px]">
      <Star className="size-2.5 fill-warn/85 text-warn/85" />
      {favorites.slice(0, 4).map((row) => (
        <Button key={row.code} size="compact" onClick={() => onPick(row.code)}>
          {label(row)}
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
              {favorites.map((row) => (
                <Menu.Item
                  key={row.code}
                  onSelect={() => onPick(row.code)}
                  className="cursor-pointer rounded-md px-2.5 py-1.5 text-xs outline-none data-[highlighted]:bg-accent"
                >
                  {label(row)} · {row.code}
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
