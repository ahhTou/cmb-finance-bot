import * as AlertPrimitive from '@radix-ui/react-alert-dialog'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { type ReactNode, useEffect } from 'react'
import { cn } from '../../lib/utils'
import { useUI } from '../../store'
import { Toast } from '../Toast'
import { Button } from './button'

const overlay = 'fixed inset-0 z-40 bg-black/45 backdrop-blur-[2px] data-[state=open]:animate-overlay-in'

function useCountOpen(open: boolean) {
  const dialogOpened = useUI((s) => s.dialogOpened)
  useEffect(() => (open ? dialogOpened() : undefined), [open, dialogOpened])
}

const content =
  'fixed top-1/2 left-1/2 z-50 flex max-h-[calc(100vh-48px)] -translate-x-1/2 -translate-y-1/2 flex-col ' +
  'rounded-2xl bg-bg shadow-[0_24px_60px_rgb(0_0_0/0.55)] ring-1 ring-white/8 outline-none ' +
  'data-[state=open]:animate-dialog-in'

/** Sheet-style dialog. `width`/`height` are in px, like the native sheets. */
export function Dialog({
  open,
  onOpenChange,
  title,
  subtitle,
  actions,
  children,
  width = 520,
  height,
  dismissable = true,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  subtitle?: string
  actions?: ReactNode
  children: ReactNode
  width?: number
  height?: number
  dismissable?: boolean
}) {
  useCountOpen(open)
  return (
    <DialogPrimitive.Root open={open} onOpenChange={(value) => (dismissable || value) && onOpenChange(value)}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className={overlay} />
        <DialogPrimitive.Content
          className={cn(content, 'gap-4 p-6')}
          style={{ width: `min(${width}px, calc(100vw - 48px))`, height }}
          onInteractOutside={(event) => !dismissable && event.preventDefault()}
          onEscapeKeyDown={(event) => !dismissable && event.preventDefault()}
          aria-describedby={undefined}
        >
          <div className="flex items-center gap-2">
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <DialogPrimitive.Title className="font-semibold text-[17px]">{title}</DialogPrimitive.Title>
              {subtitle && <p className="text-[11px] text-muted">{subtitle}</p>}
            </div>
            {actions}
            <DialogPrimitive.Close asChild>
              <Button disabled={!dismissable}>关闭</Button>
            </DialogPrimitive.Close>
          </div>
          {children}
          <Toast inDialog top={64} />
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}

/** Two-button confirmation, like SwiftUI's destructive alert. */
export function Confirm({
  open,
  onOpenChange,
  title,
  message,
  cancel,
  confirm,
  onConfirm,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  message: string
  cancel: string
  confirm: string
  onConfirm: () => void
}) {
  useCountOpen(open)
  return (
    <AlertPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <AlertPrimitive.Portal>
        <AlertPrimitive.Overlay className={overlay} />
        <AlertPrimitive.Content className={cn(content, 'w-[340px] gap-3 p-6 text-center')}>
          <AlertPrimitive.Title className="font-semibold text-[15px]">{title}</AlertPrimitive.Title>
          <AlertPrimitive.Description className="text-muted text-xs leading-relaxed">
            {message}
          </AlertPrimitive.Description>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <AlertPrimitive.Cancel asChild>
              <Button>{cancel}</Button>
            </AlertPrimitive.Cancel>
            <AlertPrimitive.Action asChild>
              <Button variant="primary" onClick={onConfirm}>
                {confirm}
              </Button>
            </AlertPrimitive.Action>
          </div>
        </AlertPrimitive.Content>
      </AlertPrimitive.Portal>
    </AlertPrimitive.Root>
  )
}
