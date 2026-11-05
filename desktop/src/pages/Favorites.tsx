import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import { api } from '../api/client'
import { useAction, useWatch } from '../api/hooks'
import type { Favorite } from '../api/types'
import { TestTag } from '../components/shared'
import { Button } from '../components/ui/button'
import { Card } from '../components/ui/card'
import { Confirm, Dialog } from '../components/ui/dialog'
import { Field, Input } from '../components/ui/form'
import { validAmount, validCode } from '../lib/utils'
import { useUI } from '../store'

export function FavoritesPage() {
  const { favorites } = useWatch()
  const busy = useUI((s) => s.busy)
  const action = useAction()
  const [code, setCode] = useState('')
  const [title, setTitle] = useState('')
  const [removing, setRemoving] = useState<string | null>(null)
  const [testing, setTesting] = useState<Favorite | null>(null)
  const [testDraft, setTestDraft] = useState('0.01')
  const canAdd = validCode(code) && title.trim() !== ''

  function add() {
    const body = { code: code.trim(), title: title.trim() }
    setCode('')
    setTitle('')
    action('添加收藏', () => api('POST', '/api/favorites', body))
  }

  function configureTest(row: Favorite) {
    setTesting(row)
    setTestDraft(row.test_amount ?? '0.01')
  }

  async function saveTest() {
    const row = testing
    if (!row || !validAmount(testDraft.trim())) return
    const ok = await action(row.test_amount ? '更新测试项' : '设为测试项', () =>
      api('POST', '/api/favorites/test', { code: row.code, amount: testDraft.trim() }),
    )
    if (ok) setTesting(null)
  }

  async function clearTest() {
    const ok = await action('取消测试项', () => api('DELETE', '/api/favorites/test'))
    if (ok) setTesting(null)
  }

  return (
    <div className="flex flex-col gap-4 overflow-y-auto px-[26px]">
      <Card title="添加收藏" subtitle="收藏保存产品代码和标题；可给其中一项设置测试金额，供演练自动带入。">
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
      <Card
        title="已收藏"
        subtitle={`点「设为测试」配置测试金额；演练布防和单笔购买演练会自动带入。共 ${favorites.length} 项`}
      >
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
                  <FavoriteRow
                    row={row}
                    onRemove={() => setRemoving(row.code)}
                    onTest={() => configureTest(row)}
                  />
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        )}
        <p className="text-[10px] text-muted">测试项只是默认参数，实际付款仍要在确认页勾选金额。</p>
      </Card>
      <Dialog
        open={testing !== null}
        onOpenChange={(open) => !open && setTesting(null)}
        dismissable={!busy}
        title={testing?.test_amount ? '修改测试项' : '设为测试项'}
        subtitle="同一时间只有一项；只在演练时作为默认参数。"
        width={460}
      >
        <div className="flex items-center gap-3">
          <span className="shrink-0 font-mono text-xs">{testing?.code}</span>
          <Field label="测试金额">
            <Input
              data-testid="test-amount-input"
              inputMode="decimal"
              placeholder="0.01"
              value={testDraft}
              onChange={(e) => setTestDraft(e.target.value)}
              autoFocus
            />
          </Field>
        </div>
        <p className="text-[10px] text-muted">测试项不构成付款授权；实际付款仍要在确认页勾选金额。</p>
        <div className="flex items-center justify-end gap-2.5">
          {testing?.test_amount && (
            <Button variant="ghost" className="mr-auto text-accent" disabled={busy} onClick={clearTest}>
              取消测试
            </Button>
          )}
          <Button disabled={busy} onClick={() => setTesting(null)}>
            取消
          </Button>
          <Button variant="primary" disabled={busy || !validAmount(testDraft.trim())} onClick={saveTest}>
            保存测试项
          </Button>
        </div>
      </Dialog>
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

function FavoriteRow({ row, onRemove, onTest }: { row: Favorite; onRemove: () => void; onTest: () => void }) {
  const busy = useUI((s) => s.busy)
  const action = useAction()
  const [draft, setDraft] = useState(row.title ?? '')

  return (
    <div className="flex items-center gap-3 py-[7px]">
      <div className="flex w-24 shrink-0 flex-col items-start gap-[3px]">
        <span className="font-medium font-mono text-xs">{row.code}</span>
        {row.test_amount && <TestTag amount={row.test_amount} testId={`test-tag-${row.code}`} />}
      </div>
      <div className="min-w-0 flex-1">
        <Input
          aria-label={`${row.code} 标题`}
          placeholder="标题"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
      </div>
      <Button
        disabled={busy || draft.trim() === ''}
        onClick={() =>
          action('修改标题', () => api('POST', '/api/favorites', { code: row.code, title: draft.trim() }))
        }
      >
        保存标题
      </Button>
      <Button data-testid={`set-test-${row.code}`} disabled={busy} onClick={onTest}>
        {row.test_amount ? '修改测试' : '设为测试'}
      </Button>
      <Button className="text-accent" onClick={onRemove}>
        删除
      </Button>
    </div>
  )
}
