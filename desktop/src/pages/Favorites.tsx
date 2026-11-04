import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import { api } from '../api/client'
import { useAction, useWatch } from '../api/hooks'
import type { Favorite } from '../api/types'
import { Button } from '../components/ui/button'
import { Card } from '../components/ui/card'
import { Confirm } from '../components/ui/dialog'
import { Field, Input } from '../components/ui/form'
import { validCode } from '../lib/utils'
import { useUI } from '../store'

export function FavoritesPage() {
  const { favorites } = useWatch()
  const busy = useUI((s) => s.busy)
  const action = useAction()
  const [code, setCode] = useState('')
  const [title, setTitle] = useState('')
  const [removing, setRemoving] = useState<string | null>(null)
  const canAdd = validCode(code) && title.trim() !== ''

  function add() {
    const body = { code: code.trim(), title: title.trim() }
    setCode('')
    setTitle('')
    action('添加收藏', () => api('POST', '/api/favorites', body))
  }

  return (
    <div className="flex flex-col gap-4 overflow-y-auto px-[26px]">
      <Card title="添加收藏" subtitle="只保存产品代码和标题，不保存金额、时间或凭据。">
        <form
          className="flex items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (canAdd && !busy) add()
          }}
        >
          <Field label="产品代码">
            <Input placeholder="如 JX040229" value={code} onChange={(e) => setCode(e.target.value)} />
          </Field>
          <Field label="标题">
            <Input placeholder="如 招睿丰和 30 天" value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Button type="submit" variant="primary" className="h-[38px]" disabled={!canAdd || busy}>
            添加
          </Button>
        </form>
      </Card>
      <Card title="已收藏" subtitle={`布防和单笔演练都能直接选；共 ${favorites.length} 项`}>
        {favorites.length === 0 ? (
          <p className="text-muted text-xs">还没有收藏。添加后，填产品代码的地方会出现快捷选择。</p>
        ) : (
          <ul className="flex flex-col">
            <AnimatePresence initial={false}>
              {favorites.map((row) => (
                <motion.li
                  key={row.code}
                  layout
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ type: 'spring', stiffness: 400, damping: 36 }}
                  className="overflow-hidden border-white/6 border-b"
                >
                  <FavoriteRow row={row} onRemove={() => setRemoving(row.code)} />
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        )}
      </Card>
      <Confirm
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title="删除收藏？"
        message="只删除本地收藏，不影响银行里的产品。"
        cancel="取消"
        confirm="删除"
        onConfirm={() => {
          const value = removing
          setRemoving(null)
          if (value) action('删除收藏', () => api('DELETE', `/api/favorites/${encodeURIComponent(value)}`))
        }}
      />
    </div>
  )
}

function FavoriteRow({ row, onRemove }: { row: Favorite; onRemove: () => void }) {
  const busy = useUI((s) => s.busy)
  const action = useAction()
  const [draft, setDraft] = useState(row.title ?? '')
  return (
    <div className="flex items-center gap-3 py-[7px]">
      <span className="w-24 shrink-0 font-medium font-mono text-xs">{row.code}</span>
      <Input
        aria-label={`${row.code} 标题`}
        placeholder="标题"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
      />
      <Button
        disabled={busy || draft.trim() === ''}
        onClick={() =>
          action('修改标题', () => api('POST', '/api/favorites', { code: row.code, title: draft.trim() }))
        }
      >
        保存标题
      </Button>
      <Button className="text-accent" onClick={onRemove}>
        删除
      </Button>
    </div>
  )
}
