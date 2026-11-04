import { CircleAlert, Copy, X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { copyText } from '../lib/utils'
import { useUI } from '../store'
import { Button } from './ui/button'

/**
 * Error toast in the top-right corner, springing in like the native one. A modal
 * dialog hides and blocks everything outside it, so each dialog renders its own
 * toast (as the native sheets did) and the window-level one steps aside.
 */
export function Toast({ top = 82, inDialog = false }: { top?: number; inDialog?: boolean }) {
  const message = useUI((s) => (inDialog || s.dialogs === 0 ? s.message : null))
  const setMessage = useUI((s) => s.setMessage)
  return (
    <AnimatePresence>
      {message && (
        <motion.div
          role="alert"
          initial={{ opacity: 0, y: -12, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -8, scale: 0.98 }}
          transition={{ type: 'spring', stiffness: 420, damping: 30 }}
          style={{ top }}
          className="fixed right-5 z-[60] flex w-[400px] max-w-[calc(100vw-40px)] flex-col gap-2.5 rounded-xl bg-button p-4 shadow-[0_5px_24px_rgb(0_0_0/0.3)]"
        >
          <div className="flex items-center gap-2">
            <CircleAlert className="size-4 text-accent" />
            <span className="flex-1 font-semibold text-xs">操作提示</span>
            <Button variant="ghost" size="icon" aria-label="复制完整提示" onClick={() => copyText(message)}>
              <Copy className="size-3.5" />
            </Button>
            <Button variant="ghost" size="icon" aria-label="关闭提示" onClick={() => setMessage(null)}>
              <X className="size-3.5" />
            </Button>
          </div>
          <p className="selectable max-h-[140px] overflow-y-auto text-xs leading-relaxed">{message}</p>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
