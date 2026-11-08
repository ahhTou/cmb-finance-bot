import { Star } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useRef, useState } from 'react'
import { api } from '../api/client'
import { useAction, useWatch } from '../api/hooks'
import type { Favorite, FavoriteSettingsRequest, QuotaKind, QuotaTime } from '../api/types'
import { TestTag } from '../components/shared'
import { Button } from '../components/ui/button'
import { Badge, Card, Hint } from '../components/ui/card'
import { Confirm, Dialog } from '../components/ui/dialog'
import { Checkbox, Field, Input, Select } from '../components/ui/form'
import {
  emptyQuotaTime,
  isQuotaExpired,
  KIND_TEXT,
  KIND_TONE,
  MAX_QUOTA_TIMES,
  NOTE_MAX,
  quotaAmountText,
  quotaEntriesOf,
  quotaTimeText,
  validQuotaAmount,
  validQuotaDate,
  validQuotaTime,
  WEEKDAY_TEXT,
} from '../lib/favorites'
import { cn, validAmount, validCode } from '../lib/utils'
import { useUI } from '../store'

const QUOTA_KINDS: QuotaKind[] = ['issue', 'bargain', 'regular']
const WEEKDAYS = [1, 2, 3, 4, 5, 6, 7]
/** 额度时间只是参考；服务端不会按它布防或购买。 */
const QUOTA_NOTE = '额度时间仅供参考，不会自动布防或购买。'

/** One editable quota-time row; `key` is local to the dialog and never saved. */
interface QuotaDraftRow {
  key: string
  id?: string
  kind: QuotaKind
  date: string
  time: string
  weekdays: number[]
  amount: string
  amountUnset: boolean
  note: string
}

interface SettingsDraft {
  row: Favorite
  testChecked: boolean
  testAmount: string
  quota: QuotaDraftRow[]
}

function quotaDraft(entry: QuotaTime, key: string): QuotaDraftRow {
  return {
    key,
    id: entry.id,
    kind: entry.kind,
    date: entry.date ?? '',
    time: entry.time,
    weekdays: entry.weekdays ?? [],
    amount: entry.amount_wan ?? '',
    amountUnset: !entry.amount_wan,
    note: entry.note ?? '',
  }
}

/** Canonical PUT entry per contract §1: only the fields the chosen kind uses. */
function quotaPayload(row: QuotaDraftRow): QuotaTime {
  const entry: QuotaTime = { kind: row.kind, time: row.time.trim() }
  if (row.id) entry.id = row.id
  if (row.kind === 'issue') entry.date = row.date
  else entry.weekdays = [...new Set(row.weekdays)].sort((left, right) => left - right)
  if (!row.amountUnset) entry.amount_wan = row.amount.trim()
  const note = row.note.trim()
  if (note) entry.note = note
  return entry
}

/** First local problem of one row, or null when it is ready to save. */
function quotaProblem(row: QuotaDraftRow): string | null {
  if (row.kind === 'issue') {
    if (!row.date) return '请选择首发日期。'
    if (!validQuotaDate(row.date)) return '首发日期格式不正确。'
  } else if (row.weekdays.length === 0) return '请至少选择一个星期。'
  if (!row.time) return '请填写时刻。'
  if (!validQuotaTime(row.time)) return '时刻格式不正确。'
  if (!row.amountUnset) {
    if (!row.amount.trim()) return '请填写额度数量。'
    if (!validQuotaAmount(row.amount)) return '额度数量须为大于 0 的数字，最多两位小数，且不超过 1000000 万。'
  }
  if ([...row.note].length > NOTE_MAX) return `备注最多 ${NOTE_MAX} 个字符。`
  return null
}

export function FavoritesPage() {
  const { favorites } = useWatch()
  const busy = useUI((s) => s.busy)
  const action = useAction()
  const [code, setCode] = useState('')
  const [title, setTitle] = useState('')
  const [removing, setRemoving] = useState<string | null>(null)
  const [settings, setSettings] = useState<SettingsDraft | null>(null)
  const keySeq = useRef(0)
  function newKey() {
    keySeq.current += 1
    return `quota-${keySeq.current}`
  }
  const canAdd = validCode(code) && title.trim() !== ''

  const problems: string[] = []
  if (settings) {
    if (settings.testChecked && !validAmount(settings.testAmount.trim())) {
      problems.push('测试金额须为大于 0 的数字，最多两位小数。')
    }
    settings.quota.forEach((row, index) => {
      const problem = quotaProblem(row)
      if (problem) problems.push(`第 ${index + 1} 条：${problem}`)
    })
  }
  const otherTest = settings
    ? favorites.find((row) => row.code !== settings.row.code && Boolean(row.test_amount))
    : undefined

  function add() {
    const body = { code: code.trim(), title: title.trim() }
    setCode('')
    setTitle('')
    action('添加收藏', () => api('POST', '/api/favorites', body))
  }

  function openSettings(row: Favorite) {
    setSettings({
      row,
      testChecked: Boolean(row.test_amount),
      testAmount: row.test_amount ?? '0.01',
      quota: quotaEntriesOf(row).map((entry) => quotaDraft(entry, newKey())),
    })
  }

  function patchSettings(changes: Partial<SettingsDraft>) {
    setSettings((current) => (current ? { ...current, ...changes } : current))
  }

  function patchQuota(index: number, changes: Partial<QuotaDraftRow>) {
    setSettings((current) =>
      current
        ? {
            ...current,
            quota: current.quota.map((row, rowIndex) => (rowIndex === index ? { ...row, ...changes } : row)),
          }
        : current,
    )
  }

  function addQuota() {
    if (!settings || settings.quota.length >= MAX_QUOTA_TIMES) return
    patchSettings({ quota: [...settings.quota, quotaDraft(emptyQuotaTime(), newKey())] })
  }

  function removeQuota(index: number) {
    if (!settings) return
    patchSettings({ quota: settings.quota.filter((_, rowIndex) => rowIndex !== index) })
  }

  async function saveSettings() {
    const draft = settings
    if (!draft || problems.length > 0) return
    const body: FavoriteSettingsRequest = {
      test_amount: draft.testChecked ? draft.testAmount.trim() : null,
      quota_times: draft.quota.map(quotaPayload),
    }
    const ok = await action('保存收藏设置', () =>
      api('PUT', `/api/favorites/${encodeURIComponent(draft.row.code)}`, body),
    )
    if (ok) setSettings(null)
  }

  return (
    <div className="flex flex-col gap-4 overflow-y-auto px-[26px]">
      <Card
        title="添加收藏"
        subtitle="收藏保存产品代码和标题；设置里可标记测试项，并记录额度时间（仅作参考）。"
      >
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
        subtitle={`点「设置」配置测试项和额度时间；额度时间只记录参考，不会自动布防或购买。共 ${favorites.length} 项`}
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
                    onSettings={() => openSettings(row)}
                  />
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        )}
        <p className="text-[10px] text-muted">测试项只是默认参数，实际付款仍要在确认页勾选金额。</p>
      </Card>
      <Dialog
        open={settings !== null}
        onOpenChange={(open) => !open && !busy && setSettings(null)}
        dismissable={!busy}
        title={settings ? `设置 · ${settings.row.code}` : '设置'}
        subtitle={settings ? `${settings.row.title || settings.row.code} · ${QUOTA_NOTE}` : undefined}
        width={640}
      >
        {settings && (
          <div data-testid="favorite-settings-dialog" className="flex min-h-0 flex-1 flex-col gap-4">
            <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-1">
              <section className="flex flex-col gap-2">
                <h3 className="font-medium text-xs">测试项</h3>
                <Checkbox
                  testId="test-item-check"
                  checked={settings.testChecked}
                  onChange={(value) => patchSettings({ testChecked: value })}
                  label="设为测试项（演练自动带入金额）"
                  disabled={busy}
                />
                <div className="flex items-center gap-2 pl-6">
                  <Input
                    data-testid="test-amount-input"
                    className="h-[32px] w-28"
                    inputMode="decimal"
                    placeholder="0.01"
                    value={settings.testAmount}
                    disabled={!settings.testChecked || busy}
                    onChange={(event) => patchSettings({ testAmount: event.target.value })}
                  />
                  <span className="text-[11px] text-muted">元</span>
                </div>
                {settings.testChecked && otherTest && (
                  <Hint>当前测试项是 {otherTest.code}；保存后测试项会移到本收藏。</Hint>
                )}
              </section>
              <section className="flex flex-col gap-2">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="font-medium text-xs">额度时间</h3>
                  <Button
                    data-testid="quota-add"
                    size="compact"
                    disabled={busy || settings.quota.length >= MAX_QUOTA_TIMES}
                    onClick={addQuota}
                  >
                    添加条目
                  </Button>
                </div>
                {settings.quota.length === 0 ? (
                  <p className="text-muted text-xs">
                    还没有额度时间；点「添加条目」记录首发、捡漏或常规时间。
                  </p>
                ) : (
                  <div className="flex flex-col gap-2">
                    {settings.quota.map((row, index) => (
                      <QuotaEditor
                        key={row.key}
                        row={row}
                        index={index}
                        busy={busy}
                        onPatch={(changes) => patchQuota(index, changes)}
                        onRemove={() => removeQuota(index)}
                      />
                    ))}
                  </div>
                )}
              </section>
            </div>
            {problems.length > 0 && (
              <div data-testid="favorite-settings-problems" className="flex flex-col gap-1">
                {problems.map((problem) => (
                  <Hint key={problem} tone="warn">
                    {problem}
                  </Hint>
                ))}
              </div>
            )}
            <div className="flex items-center justify-end gap-2.5">
              <Button disabled={busy} onClick={() => setSettings(null)}>
                取消
              </Button>
              <Button
                data-testid="save-favorite-settings"
                variant="primary"
                disabled={busy || problems.length > 0}
                onClick={saveSettings}
              >
                保存设置
              </Button>
            </div>
          </div>
        )}
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

function FavoriteRow({
  row,
  onRemove,
  onSettings,
}: {
  row: Favorite
  onRemove: () => void
  onSettings: () => void
}) {
  const busy = useUI((s) => s.busy)
  const action = useAction()
  const [draft, setDraft] = useState(row.title ?? '')
  const entries = quotaEntriesOf(row)

  return (
    <div className="flex flex-col gap-1.5 py-2">
      <div className="flex items-center gap-3">
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
        <Button data-testid={`favorite-settings-${row.code}`} disabled={busy} onClick={onSettings}>
          设置
        </Button>
        <Button className="text-accent" onClick={onRemove}>
          删除
        </Button>
      </div>
      <div data-testid={`quota-times-${row.code}`} className="pl-[108px]">
        {entries.length === 0 ? (
          <p className="text-[11px] text-muted">未设置额度时间</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {entries.map((entry, index) => (
              <li
                key={
                  entry.id ?? `${entry.kind}-${entry.time}-${entry.date ?? entry.weekdays?.join('-') ?? ''}`
                }
                data-testid={`quota-entry-${row.code}-${index}`}
                className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[11px]"
              >
                <Badge tone={KIND_TONE[entry.kind]}>
                  {entry.kind === 'issue' ? (
                    <span className="flex items-center gap-1">
                      <Star className="size-2.5 fill-current" strokeWidth={2.5} />
                      {KIND_TEXT[entry.kind]}
                    </span>
                  ) : (
                    KIND_TEXT[entry.kind]
                  )}
                </Badge>
                <span className="tabular-nums">{quotaTimeText(entry)}</span>
                <span className="text-[#ebebeb]">{quotaAmountText(entry)}</span>
                {entry.note && (
                  <span className="min-w-0 max-w-full truncate text-muted" title={entry.note}>
                    {entry.note}
                  </span>
                )}
                {isQuotaExpired(entry) && <Badge tone="warn">已过期</Badge>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function QuotaEditor({
  row,
  index,
  busy,
  onPatch,
  onRemove,
}: {
  row: QuotaDraftRow
  index: number
  busy: boolean
  onPatch: (changes: Partial<QuotaDraftRow>) => void
  onRemove: () => void
}) {
  const weekly = row.kind !== 'issue'
  const timeInput = (
    <Input
      data-testid={`quota-time-${index}`}
      type="time"
      className="h-[30px] w-[128px]"
      value={row.time}
      disabled={busy}
      onChange={(event) => onPatch({ time: event.target.value })}
    />
  )

  return (
    <div className="flex flex-col gap-2 rounded-xl bg-field px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <Select
          data-testid={`quota-kind-${index}`}
          className="h-[30px]"
          value={row.kind}
          disabled={busy}
          onChange={(event) => onPatch({ kind: event.target.value as QuotaKind })}
        >
          {QUOTA_KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {KIND_TEXT[kind]}
            </option>
          ))}
        </Select>
        {weekly ? (
          <>
            {WEEKDAYS.map((day) => {
              const on = row.weekdays.includes(day)
              return (
                <button
                  key={day}
                  type="button"
                  aria-pressed={on}
                  data-testid={`quota-weekday-${index}-${day}`}
                  disabled={busy}
                  onClick={() =>
                    onPatch({
                      weekdays: on ? row.weekdays.filter((value) => value !== day) : [...row.weekdays, day],
                    })
                  }
                  className={cn(
                    'h-[26px] rounded-md px-2 font-medium text-[11px] transition-colors',
                    on ? 'bg-accent text-white' : 'bg-button text-muted hover:text-fg',
                    busy && 'opacity-45',
                  )}
                >
                  {WEEKDAY_TEXT[day]}
                </button>
              )
            })}
            {timeInput}
          </>
        ) : (
          <>
            <Input
              data-testid={`quota-date-${index}`}
              type="date"
              className="h-[30px] w-[150px]"
              value={row.date}
              disabled={busy}
              onChange={(event) => onPatch({ date: event.target.value })}
            />
            {timeInput}
          </>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] text-muted">额度</span>
        <Input
          data-testid={`quota-amount-${index}`}
          className="h-[30px] w-24"
          inputMode="decimal"
          placeholder="如 5000"
          value={row.amount}
          disabled={busy || row.amountUnset}
          onChange={(event) => onPatch({ amount: event.target.value })}
        />
        <span className="text-[11px] text-muted">万</span>
        <Checkbox
          testId={`quota-amount-unset-${index}`}
          checked={row.amountUnset}
          onChange={(value) => onPatch({ amountUnset: value })}
          label="不定额度"
          disabled={busy}
        />
        <Input
          data-testid={`quota-note-${index}`}
          className="h-[30px] min-w-[120px] flex-1"
          placeholder="备注（可选，最多 100 字）"
          maxLength={NOTE_MAX}
          value={row.note}
          disabled={busy}
          onChange={(event) => onPatch({ note: event.target.value })}
        />
        <Button
          data-testid={`quota-remove-${index}`}
          size="compact"
          variant="ghost"
          className="text-accent"
          disabled={busy}
          onClick={onRemove}
        >
          删除
        </Button>
      </div>
    </div>
  )
}
