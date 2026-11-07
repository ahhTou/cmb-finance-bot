import { useQuery, useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { q, useAction } from '../api/hooks'
import type { Mode, PlanItem, PlanRequest, PlanStartRequest, PlanView } from '../api/types'
import { FavoritePicker, LogText } from '../components/shared'
import { Button } from '../components/ui/button'
import { Badge, Card, Hint, Metric, MetricGrid } from '../components/ui/card'
import { Dialog } from '../components/ui/dialog'
import { Checkbox, Field, Input, Segmented, Select, Switch } from '../components/ui/form'
import {
  countdownText,
  draftFromPlan,
  draftItemProblem,
  draftProblems,
  emptyDraftItem,
  isoClock,
  itemInputToISO,
  itemStatus,
  nextItem,
  PLAN_MAX_ITEMS,
  type PlanDraftItem,
  planDirty,
  planStatus,
  planTotals,
  statusPrimaryName,
  statusPrimaryTone,
  statusSecondaryName,
} from '../lib/plan'
import { cn, parseLocal, toneBg } from '../lib/utils'
import { useUI } from '../store'

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
const pad2 = (value: number) => String(value).padStart(2, '0')

function startOfDay(value: Date) {
  const copy = new Date(value)
  copy.setHours(0, 0, 0, 0)
  return copy
}

function addDays(value: Date, days: number) {
  const copy = new Date(value)
  copy.setDate(copy.getDate() + days)
  return copy
}

function sameDay(left: Date, right: Date) {
  return (
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate()
  )
}

function dayLabel(value: Date) {
  return `${pad2(value.getMonth() + 1)}-${pad2(value.getDate())}`
}

function weekdayLabel(value: Date) {
  return WEEKDAYS[value.getDay()]
}

/**
 * Plan mode: one saved plan is a list of purchase times. The backend computes
 * each cold-start and expected end time, then runs the items strictly in order,
 * so this page never schedules anything locally.
 */
export function PlanPage() {
  const { data: view, error } = useQuery(q.plan)
  const qc = useQueryClient()
  const action = useAction()
  const busy = useUI((s) => s.busy)
  const [draft, setDraft] = useState<PlanDraftItem[] | null>(null)
  const [dryRun, setDryRun] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [confirmation, setConfirmation] = useState<PlanView | null>(null)
  const [now, setNow] = useState(() => new Date())
  const [editingTerminal, setEditingTerminal] = useState(false)
  const [viewMode, setViewMode] = useState<'timeline' | 'week'>('timeline')
  const [weekStart, setWeekStart] = useState(() => startOfDay(new Date()))

  // The status card shows a countdown; a one-second tick is enough.
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  // Seed the editor from the first read. Saves and cancels replace it explicitly,
  // so a background refresh never overwrites what is being typed.
  useEffect(() => {
    if (!view || draft !== null) return
    setDraft(draftFromPlan(view.plan))
    setDryRun(view.plan?.dry_run ?? false)
  }, [view, draft])

  const plan = view?.plan ?? null
  const running = view?.running === true
  const stale = view?.stale === true
  const heartbeatStale = view?.heartbeat_stale === true
  const settingsChanged = view?.settings_changed === true
  const phase = plan?.phase ?? null
  const status = view?.status ?? plan?.status ?? planStatus(plan, now)
  const secondary = statusSecondaryName(status)
  const terminal =
    !!plan && !running && !stale && (phase === 'done' || phase === 'aborted' || phase === 'disarmed')
  const resultView = terminal && !editingTerminal
  const readOnly = running || stale || resultView
  const problems = view?.problems ?? []
  const warnings = view?.warnings ?? []
  const totals = planTotals(plan)
  const next = nextItem(plan)
  const confirmPlan = confirmation?.plan ?? null
  const confirmTotals = planTotals(confirmPlan)
  const confirmDryRun = confirmPlan?.dry_run ?? false
  const rows = resultView ? draftFromPlan(plan) : (draft ?? [])
  const localProblems = resultView ? [] : draftProblems(draft ?? [])
  const dirty = resultView ? false : planDirty(draft ?? [], dryRun, plan)
  const datedRows = rows.map((row, index) => ({
    row,
    index,
    at: parseLocal(itemInputToISO(row.at)),
  }))
  const timelineGroups = new Map<string, { date: Date | null; rows: typeof datedRows }>()
  for (const entry of datedRows) {
    const key = entry.at
      ? `${entry.at.getFullYear()}-${pad2(entry.at.getMonth() + 1)}-${pad2(entry.at.getDate())}`
      : 'undated'
    const group = timelineGroups.get(key) ?? { date: entry.at, rows: [] }
    group.rows.push(entry)
    timelineGroups.set(key, group)
  }
  const orderedTimeline = [...timelineGroups.entries()].sort(([left, a], [right, b]) => {
    if (left === 'undated') return 1
    if (right === 'undated') return -1
    return (a.date?.getTime() ?? 0) - (b.date?.getTime() ?? 0)
  })
  const weekDays = Array.from({ length: 7 }, (_, index) => addDays(weekStart, index))
  const weekEnd = addDays(weekStart, 7)
  const weekRows = datedRows.filter(
    (entry) =>
      entry.at && entry.at.getTime() >= weekStart.getTime() && entry.at.getTime() < weekEnd.getTime(),
  )
  // The backend always recomputes `problems` against "now", so after the first
  // item's purchase time they would read "已过" while the plan is running fine.
  // They only block starting, so the page treats them as blockers while idle.
  const canStartPhase = !running && !stale && (phase === null || phase === 'idle')
  const blockingProblems = canStartPhase ? problems : []
  const finished =
    plan?.items.filter((item) => ['done', 'failed', 'skipped'].includes(item.state ?? '')).length ?? 0
  const canStart =
    phase === 'idle' &&
    !dirty &&
    rows.length > 0 &&
    localProblems.length === 0 &&
    blockingProblems.length === 0 &&
    !busy

  function applied(result: PlanView | null) {
    if (!result) return
    qc.setQueryData(q.plan.queryKey, result)
    setDraft(draftFromPlan(result.plan))
    setDryRun(result.plan?.dry_run ?? false)
    setEditingTerminal(false)
  }

  async function run(label: string, request: () => Promise<PlanView>) {
    const result = await action(label, request)
    applied(result)
    return result
  }

  async function save() {
    if (localProblems.length) {
      useUI.getState().setMessage(localProblems[0])
      return
    }
    const body: PlanRequest = {
      dry_run: dryRun,
      items: (draft ?? []).map((item) => ({
        code: item.code.trim(),
        amount: item.amount.trim(),
        at: itemInputToISO(item.at),
        mode: item.mode,
      })),
    }
    await run('保存计划', () => api<PlanView>('PUT', '/api/plan', body))
  }

  function openConfirm() {
    if (!canStart) return
    if (!plan?.plan_id || !plan.content_revision || !view?.settings_revision) {
      useUI.getState().setMessage('缺少计划确认版本，请刷新计划后重试。')
      return
    }
    // Freeze both the displayed list and the exact versions this confirmation authorizes.
    setConfirmation(structuredClone(view))
    setConfirmed(false)
    setConfirming(true)
  }

  async function startNow() {
    if (!confirmPlan?.plan_id || !confirmPlan.content_revision || !confirmation?.settings_revision) return
    const body: PlanStartRequest = {
      plan_id: confirmPlan.plan_id,
      content_revision: confirmPlan.content_revision,
      settings_revision: confirmation.settings_revision,
      confirm_real_payment: !confirmDryRun && confirmed,
    }
    const result = await run(confirmDryRun ? '开始演练计划' : '开始真实计划', () =>
      api<PlanView>('POST', '/api/plan/start', body),
    )
    setConfirming(false)
    if (!result) await qc.invalidateQueries({ queryKey: q.plan.queryKey })
  }

  async function disarm() {
    await run('取消计划', () => api<PlanView>('POST', '/api/plan/disarm'))
  }

  async function clear() {
    await run('清空计划', () => api<PlanView>('DELETE', '/api/plan'))
  }

  function editTerminal() {
    if (!plan) return
    setDraft(draftFromPlan(plan))
    setDryRun(plan.dry_run ?? false)
    setEditingTerminal(true)
  }

  function patch(index: number, changes: Partial<PlanDraftItem>) {
    // Editing invalidates the backend-computed times and item state for this row.
    setDraft((current) =>
      current
        ? current.map((row, position) => (position === index ? { ...row, ...changes, saved: null } : row))
        : current,
    )
  }

  function add() {
    setDraft((current) => [...(current ?? []), emptyDraftItem(current?.at(-1)?.mode ?? 'first_launch')])
  }

  function remove(index: number) {
    setDraft((current) => (current ? current.filter((_, position) => position !== index) : current))
  }

  if (!view) {
    return (
      <div className="flex flex-col gap-3.5 overflow-y-auto px-[26px] pb-2">
        <Card title="计划状态" subtitle="计划模式 · 多个布防自动排程">
          {error ? <Hint tone="warn">{error.message}</Hint> : <Hint>正在读取计划…</Hint>}
        </Card>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3.5 overflow-y-auto px-[26px] pb-2">
      <Card
        title="计划状态"
        subtitle={
          running
            ? '计划正在按时间顺序执行；下方列表只读，可随时取消。'
            : resultView
              ? '计划已结束；这里保留每项状态、原因和实际时间。'
              : '只填购买时间；保存后程序算出每项的冷启动与预计结束时间。'
        }
      >
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <div data-testid="plan-status" className="flex flex-wrap items-center gap-2">
            <Badge tone={statusPrimaryTone(status)}>{statusPrimaryName(status)}</Badge>
            {secondary && <Badge tone="muted">{secondary}</Badge>}
            {plan && (
              <Badge tone={plan.dry_run ? 'purple' : 'accent'}>
                {plan.dry_run ? '演练计划' : '真实计划'}
              </Badge>
            )}
          </div>
          <span className="text-[11px] text-muted">
            {status?.description ??
              (next
                ? `${running ? '当前项' : '下一项'} ${next.code} · ${countdownText(next.at, now)}`
                : plan
                  ? '没有待执行的布防'
                  : '还没有计划')}
          </span>
          {next && status?.description && (
            <span className="text-[11px] text-muted">
              {running ? '当前项' : '下一项'} {next.code} · {countdownText(next.at, now)}
            </span>
          )}
          <div className="ml-auto flex items-center gap-2">
            {terminal && resultView && (
              <Button data-testid="plan-edit" disabled={busy} onClick={editTerminal}>
                编辑 / 复制为新计划
              </Button>
            )}
            {terminal && editingTerminal && (
              <Button data-testid="plan-results" disabled={busy} onClick={() => setEditingTerminal(false)}>
                查看执行结果
              </Button>
            )}
            {(running || stale) && (
              <Button data-testid="plan-disarm" variant="primary" disabled={busy} onClick={disarm}>
                取消计划
              </Button>
            )}
            {!running && !stale && phase === 'idle' && (
              <Button data-testid="plan-start" variant="primary" disabled={!canStart} onClick={openConfirm}>
                开始计划
              </Button>
            )}
            {!running && !stale && plan && (
              <Button data-testid="plan-clear" disabled={busy} onClick={clear}>
                清空
              </Button>
            )}
          </div>
        </div>
        <MetricGrid>
          <Metric title="布防项" value={`${totals.count} 项`} />
          <Metric title="合计金额" value={`¥ ${totals.amount}`} />
          <Metric title="执行进度" value={plan ? `${finished} / ${plan.items.length} 项已结束` : '—'} />
          <Metric
            title="最近心跳"
            value={
              view?.heartbeat_age_s != null
                ? `${view.heartbeat_age_s} 秒前`
                : plan?.last_tick
                  ? isoClock(plan.last_tick)
                  : '—'
            }
          />
        </MetricGrid>
        {stale && (
          <Hint tone="warn">计划进程已退出，但计划仍标记为运行中。请点「取消计划」止损后重新保存。</Hint>
        )}
        {!stale && running && heartbeatStale && (
          <Hint tone="warn">
            计划进程仍在，但
            {view.heartbeat_age_s == null ? '没有心跳记录' : `已 ${view.heartbeat_age_s} 秒没有写心跳`}
            （阈值 {view.heartbeat_timeout_s ?? '—'} 秒）；只提示，不会自动重试交易，可取消计划后检查。
          </Hint>
        )}
        {settingsChanged && (running || stale) && (
          <Hint tone="warn">
            值守配置已修改：当前项按开始时的快照执行；未进入提交时会停止计划，已进入提交则等结果后停止后续项。
          </Hint>
        )}
        {settingsChanged && terminal && (
          <Hint>本计划使用开始时的配置快照；修改后的配置只影响下一份计划。</Hint>
        )}
        {(phase === 'aborted' || phase === 'disarmed') && plan?.result && (
          <Hint tone="warn">{plan.result}</Hint>
        )}
        {warnings.length > 0 && (
          <div className="flex flex-col gap-1 rounded-lg bg-warn/10 px-3 py-2">
            {warnings.map((warning) => (
              <Hint key={warning} tone="warn">
                {warning}
              </Hint>
            ))}
          </div>
        )}
      </Card>

      {blockingProblems.length > 0 && (
        <section
          data-testid="plan-problems"
          className="flex flex-col gap-1.5 rounded-[14px] bg-card p-[18px]"
        >
          <h2 className="font-semibold text-sm text-warn">还不能开始</h2>
          {blockingProblems.map((problem) => (
            <p key={problem} className="text-[11px] leading-snug text-warn/90">
              {problem}
            </p>
          ))}
          <Hint>按上面的提示修改购买时间后，再点「保存计划」。</Hint>
        </section>
      )}

      <Card
        title={resultView ? '执行结果' : '计划视图'}
        subtitle={
          resultView
            ? '逐项结果与时间来自开始时的计划快照。'
            : `最多 ${PLAN_MAX_ITEMS} 项、14 天内；程序严格按购买时间先后串行执行。`
        }
        badge={
          <Button
            data-testid="plan-add"
            size="compact"
            disabled={readOnly || busy || rows.length >= PLAN_MAX_ITEMS}
            onClick={() => {
              setViewMode('timeline')
              add()
            }}
          >
            添加布防
          </Button>
        }
      >
        <div className="flex flex-wrap items-center gap-3">
          <div className="w-[220px]">
            <Segmented
              label="计划视图"
              value={viewMode}
              options={[
                { value: 'timeline', label: '时间线' },
                { value: 'week', label: '周视图' },
              ]}
              onChange={setViewMode}
            />
          </div>
          <Hint className="text-[10px]">
            {viewMode === 'week'
              ? '周视图只读；左右切换查看全部时间段，不出现滚动条。'
              : '连续时间线；任务多时在时间线内纵向滚动。'}
          </Hint>
        </div>

        {rows.length === 0 ? (
          <p className="text-muted text-xs">
            {plan
              ? '这份计划还没有布防项。点「添加布防」添加第一项。'
              : '还没有计划。点「添加布防」填好购买时间，保存后即可开始。'}
          </p>
        ) : viewMode === 'timeline' ? (
          <TimelineView
            groups={orderedTimeline}
            readOnly={readOnly}
            resultMode={resultView}
            busy={busy}
            now={now}
            onPatch={patch}
            onRemove={remove}
          />
        ) : (
          <WeekView
            days={weekDays}
            rows={weekRows}
            now={now}
            weekStart={weekStart}
            onChangeWeek={(days) => setWeekStart(addDays(weekStart, days))}
            onToday={() => setWeekStart(startOfDay(new Date()))}
          />
        )}

        {viewMode === 'timeline' && (
          <>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              {readOnly ? (
                <Hint>
                  {resultView
                    ? '这是执行结果；点「编辑 / 复制为新计划」可基于它新建草稿。'
                    : '运行中不能修改；需要调整请先取消计划。'}
                </Hint>
              ) : (
                <>
                  <Switch
                    label="演练计划：输完交易密码不提交"
                    checked={dryRun}
                    onChange={setDryRun}
                    disabled={busy}
                  />
                  <div className="ml-auto flex items-center gap-2">
                    {dirty && <Hint>列表有未保存的修改，保存后才能开始。</Hint>}
                    <Button
                      data-testid="plan-save"
                      variant="primary"
                      disabled={busy || localProblems.length > 0}
                      onClick={save}
                    >
                      保存计划
                    </Button>
                  </div>
                </>
              )}
            </div>
            {!readOnly && localProblems.length > 0 && <Hint tone="warn">{localProblems[0]}</Hint>}
            <Hint className="text-[10px]">
              演练计划只输密码、不点确定、不提交；真实计划到点会按填写金额实际付款，开始前需勾选确认。
            </Hint>
          </>
        )}
        {viewMode === 'week' && <Hint className="text-[10px]">周视图只读；需要修改时切回「时间线」。</Hint>}
      </Card>

      {plan && (
        <Card title="计划日志" subtitle={view.log_path ?? 'var/night/plan.log'}>
          <details open={running} className="flex flex-col gap-2">
            <summary className="cursor-pointer text-[11px] text-muted">
              最近 {view.logs?.length ?? 0} 行（点击展开/收起）
            </summary>
            <LogText lines={view.logs ?? []} className="mt-2 max-h-[160px]" />
          </details>
        </Card>
      )}

      <Dialog
        open={confirming}
        onOpenChange={(open) => !open && setConfirming(false)}
        title={confirmDryRun ? '开始演练计划' : '开始真实计划'}
        subtitle={confirmDryRun ? '演练只输密码，不点确定、不提交。' : '请逐项核对产品、金额和完整购买时间。'}
        width={480}
        dismissable={!busy}
      >
        <div data-testid="plan-confirm" className="flex flex-col gap-3.5">
          <div className="flex flex-col gap-2 rounded-xl bg-field px-4 py-3">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted">布防项</span>
              <span className="font-semibold">{confirmTotals.count} 项</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-muted">
                {confirmDryRun ? '演练合计金额' : '真实支付合计'}
              </span>
              <span className="font-rounded font-semibold text-[22px]">¥ {confirmTotals.amount}</span>
            </div>
          </div>
          <ol
            data-testid="plan-confirm-items"
            className="flex max-h-[260px] list-decimal flex-col gap-2 overflow-y-auto pl-5 text-xs"
          >
            {confirmPlan?.items.map((item, index) => (
              <li key={item.item_id ?? index}>
                <span className="font-semibold">
                  {item.code} · ¥ {item.amount}
                </span>
                <div className="text-[11px] text-muted">
                  {item.mode === 'redemption' ? '不定时抢购' : '首发模式'} · {item.at.replace('T', ' ')}
                </div>
              </li>
            ))}
          </ol>
          <Hint>按核对时的计划内容及值守配置版本开始；任一版本变化都需重新核对。</Hint>
          {!confirmDryRun && (
            <Checkbox
              testId="plan-confirm-check"
              checked={confirmed}
              onChange={setConfirmed}
              label={`我已核对全部产品、金额和时间，确认真实支付 ¥${confirmTotals.amount}`}
            />
          )}
          <div className="flex justify-end gap-2.5">
            <Button disabled={busy} onClick={() => setConfirming(false)}>
              返回
            </Button>
            <Button variant="primary" disabled={busy || (!confirmDryRun && !confirmed)} onClick={startNow}>
              {confirmDryRun ? '开始演练' : '确认真实支付'}
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  )
}

/** HH:MM:SS for actual worker timestamps. */
function isoSecond(value: string | null | undefined) {
  const text = (value ?? '').trim().replace(' ', 'T')
  const match = /T(\d{2}:\d{2}:\d{2})/.exec(text)
  return match ? match[1] : isoClock(value)
}

/** Estimated cold-start wording for one saved item. */
function prepEstimate(item: PlanItem | null | undefined) {
  if (!item) return '—'
  if (item.prep_mode === 'immediate') return item.prep_text ?? '开始后立即准备'
  return item.prep_at ? `预计 ${isoClock(item.prep_at)}` : '—'
}

/** Actual cold-start wording once the worker armed the item. */
function prepActual(item: PlanItem | null | undefined) {
  if (!item?.armed_at) return null
  const lead =
    item.prep_minutes == null
      ? ''
      : item.prep_minutes === 0
        ? '（立即）'
        : `（提前 ${item.prep_minutes} 分钟）`
  return `实际 ${isoSecond(item.armed_at)}${lead}`
}

/** One-line cold-start summary for the editable/running row. */
function prepLabel(item: PlanItem | null | undefined) {
  return prepActual(item) ?? prepEstimate(item)
}

type TimelineEntry = { row: PlanDraftItem; index: number; at: Date | null }

function TimelineView({
  groups,
  readOnly,
  resultMode,
  busy,
  now,
  onPatch,
  onRemove,
}: {
  groups: [string, { date: Date | null; rows: TimelineEntry[] }][]
  readOnly: boolean
  resultMode: boolean
  busy: boolean
  now: Date
  onPatch: (index: number, changes: Partial<PlanDraftItem>) => void
  onRemove: (index: number) => void
}) {
  return (
    <div
      data-testid="plan-timeline"
      className="relative flex max-h-[54vh] min-h-[140px] flex-col gap-3 overflow-y-auto pl-5 pr-1"
    >
      <span aria-hidden className="absolute top-1 bottom-1 left-[7px] w-px bg-white/10" />
      {groups.map(([key, group]) => (
        <div key={key} className="flex flex-col gap-2">
          <div className="sticky top-0 z-10 -ml-1 w-fit rounded bg-bg/95 px-1.5 py-0.5 font-medium text-[10px] text-muted backdrop-blur">
            {group.date
              ? `${group.date.getMonth() + 1} 月 ${group.date.getDate()} 日 · ${weekdayLabel(group.date)}`
              : '未设置购买时间'}
          </div>
          {group.rows.map((entry) => {
            const status = itemStatus(entry.row.saved, now)
            const tone = statusPrimaryTone(status)
            return (
              <div key={entry.row.key} className="relative">
                <span
                  aria-hidden
                  className={cn(
                    'absolute top-[18px] -left-[14px] size-2 rounded-full ring-2 ring-bg',
                    toneBg[tone],
                  )}
                />
                <PlanRow
                  index={entry.index}
                  row={entry.row}
                  readOnly={readOnly}
                  resultMode={resultMode}
                  busy={busy}
                  now={now}
                  onPatch={onPatch}
                  onRemove={onRemove}
                />
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}

function WeekView({
  days,
  rows,
  now,
  onChangeWeek,
  onToday,
}: {
  days: Date[]
  rows: TimelineEntry[]
  now: Date
  weekStart: Date
  onChangeWeek: (days: number) => void
  onToday: () => void
}) {
  const total = rows.length
  return (
    <div data-testid="plan-week" className="flex flex-col gap-2 overflow-hidden">
      <div className="flex flex-wrap items-center gap-2">
        <Button data-testid="plan-week-prev" size="icon" aria-label="上一周" onClick={() => onChangeWeek(-7)}>
          ‹
        </Button>
        <span className="font-medium text-xs">
          {dayLabel(days[0])} – {dayLabel(days[days.length - 1])}
        </span>
        <Button data-testid="plan-week-next" size="icon" aria-label="下一周" onClick={() => onChangeWeek(7)}>
          ›
        </Button>
        <Button data-testid="plan-week-today" size="compact" onClick={onToday}>
          回到今天
        </Button>
        <span className="ml-auto text-[10px] text-muted">{total} 项</span>
      </div>
      <div className="grid h-[42vh] max-h-[420px] min-h-[240px] grid-cols-7 gap-1.5 overflow-hidden">
        {days.map((day) => {
          const dayRows = rows.filter((entry) => entry.at && sameDay(entry.at, day))
          const isToday = sameDay(day, new Date())
          return (
            <div
              key={day.toISOString()}
              data-testid={`plan-week-day-${days.indexOf(day)}`}
              data-today={isToday ? 'true' : 'false'}
              className={cn(
                'flex min-h-0 flex-col gap-1 overflow-hidden rounded-lg p-1.5',
                isToday ? 'bg-accent/10 ring-1 ring-accent/20' : 'bg-field/60',
              )}
            >
              <div className="flex shrink-0 items-center justify-between text-[10px]">
                <span className={isToday ? 'font-semibold text-accent' : 'text-muted'}>
                  {weekdayLabel(day)}
                </span>
                <span className="text-muted">{dayLabel(day)}</span>
              </div>
              <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden">
                {dayRows.map((entry) => {
                  const status = itemStatus(entry.row.saved, now)
                  const tone = statusPrimaryTone(status)
                  return (
                    <div
                      key={`${entry.row.key}-${entry.index}`}
                      className="rounded-md bg-card/70 px-1.5 py-1 text-[9px] leading-tight"
                    >
                      <div className="flex items-center gap-1 text-muted">
                        <span className={cn('size-1.5 shrink-0 rounded-full', toneBg[tone])} />
                        <span>
                          {entry.at ? `${pad2(entry.at.getHours())}:${pad2(entry.at.getMinutes())}` : '--:--'}
                        </span>
                      </div>
                      <div className="truncate font-medium text-[10px] text-fg">
                        {entry.row.code || '未填代码'}
                      </div>
                      <div className="truncate text-muted">
                        ¥ {entry.row.amount || '—'} · {statusPrimaryName(status)}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function PlanRow({
  index,
  row,
  readOnly,
  resultMode,
  busy,
  now,
  onPatch,
  onRemove,
}: {
  index: number
  row: PlanDraftItem
  readOnly: boolean
  resultMode: boolean
  busy: boolean
  now: Date
  onPatch: (index: number, changes: Partial<PlanDraftItem>) => void
  onRemove: (index: number) => void
}) {
  const saved = row.saved
  const touched = row.code.trim() !== '' || row.amount.trim() !== '' || row.at !== ''
  const problem = !readOnly && touched ? draftItemProblem(row) : null
  if (resultMode) {
    const status = itemStatus(saved, now)
    const secondary = statusSecondaryName(status)
    const result = status?.description ?? saved?.result ?? (status?.primary === 'pending' ? '未执行' : '—')
    return (
      <div
        data-testid={`plan-row-${index}`}
        className="flex flex-col gap-1.5 rounded-[10px] bg-field px-2.5 py-2"
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-5 text-[10px] text-muted tabular-nums">#{index + 1}</span>
          <span className="font-semibold text-xs">
            {row.code} · ¥ {row.amount}
          </span>
          <Badge tone={statusPrimaryTone(status)}>{statusPrimaryName(status)}</Badge>
          {secondary && <span className="text-[10px] text-muted">{secondary}</span>}
          <span className="text-[10px] text-muted">
            {row.mode === 'redemption' ? '不定时抢购' : '首发模式'} · 购买 {row.at.replace('T', ' ')}
          </span>
        </div>
        <div className="text-[10px] text-muted">
          冷启动 {prepEstimate(saved)} · {prepActual(saved) ?? '实际：未执行'} · 预计结束{' '}
          {saved?.end_at ? isoClock(saved.end_at) : '—'}
        </div>
        {(saved?.armed_at || saved?.ended_at) && (
          <div className="text-[10px] text-muted">
            实际冷启动 {saved?.armed_at ? isoSecond(saved.armed_at) : '未执行'} · 实际结束{' '}
            {saved?.ended_at ? isoSecond(saved.ended_at) : '未结束'}
          </div>
        )}
        <div
          data-testid={`plan-result-${index}`}
          className={cn(
            'text-[11px]',
            status?.primary === 'failed' || status?.primary === 'expired' || status?.primary === 'skipped'
              ? 'text-warn'
              : 'text-muted',
          )}
        >
          结果：{result}
        </div>
      </div>
    )
  }
  return (
    <div
      data-testid={`plan-row-${index}`}
      className="flex flex-col gap-2 rounded-[10px] bg-field px-2.5 py-2"
    >
      <div className="grid grid-cols-[150px_118px_minmax(90px,1fr)_100px_24px] items-end gap-2">
        <Field label="购买时间">
          <Input
            data-testid={`plan-item-at-${index}`}
            type="datetime-local"
            className="h-[34px] px-2"
            value={row.at}
            disabled={readOnly || busy}
            onChange={(event) => onPatch(index, { at: event.target.value })}
          />
        </Field>
        <Field label="模式">
          <Select
            data-testid={`plan-item-mode-${index}`}
            value={row.mode}
            disabled={readOnly || busy}
            onChange={(event) =>
              onPatch(index, {
                mode: (event.target.value === 'redemption' ? 'redemption' : 'first_launch') as Mode,
              })
            }
          >
            <option value="first_launch">首发模式</option>
            <option value="redemption">不定时抢购</option>
          </Select>
        </Field>
        <Field label="产品代码">
          <Input
            data-testid={`plan-item-code-${index}`}
            placeholder="如 JX040229"
            value={row.code}
            disabled={readOnly || busy}
            onChange={(event) => onPatch(index, { code: event.target.value })}
          />
        </Field>
        <Field label="金额">
          <Input
            data-testid={`plan-item-amount-${index}`}
            inputMode="decimal"
            placeholder="如 5000"
            value={row.amount}
            disabled={readOnly || busy}
            onChange={(event) => onPatch(index, { amount: event.target.value })}
          />
        </Field>
        {readOnly ? (
          <span aria-hidden />
        ) : (
          <Button
            data-testid={`plan-item-remove-${index}`}
            aria-label={`删除第 ${index + 1} 项`}
            size="icon"
            className="mb-[3px]"
            disabled={busy}
            onClick={() => onRemove(index)}
          >
            <X className="size-3.5" />
          </Button>
        )}
      </div>
      {!readOnly && (
        <div data-testid={`plan-item-favorites-${index}`}>
          <FavoritePicker
            onPick={(favorite) => {
              const changes: Partial<PlanDraftItem> = { code: favorite.code }
              // The test favourite also carries the drill amount; a plain one only
              // carries the product code, so never invent an amount for it.
              if (favorite.test_amount) changes.amount = favorite.test_amount
              onPatch(index, changes)
            }}
          />
        </div>
      )}
      {(saved || problem) && (
        <div className="flex flex-wrap items-center gap-2">
          {saved && (
            <span className="text-[10px] text-muted">
              冷启动 {prepLabel(saved)} · 购买 {isoClock(saved.at)} · 预计结束 {isoClock(saved.end_at)}
            </span>
          )}
          {saved && (
            <Badge tone={statusPrimaryTone(itemStatus(saved, now))}>
              {statusPrimaryName(itemStatus(saved, now))}
            </Badge>
          )}
          {saved && statusSecondaryName(itemStatus(saved, now)) && (
            <span className="text-[10px] text-muted">{statusSecondaryName(itemStatus(saved, now))}</span>
          )}
          {saved?.result && <span className="text-[10px] text-muted">{saved.result}</span>}
          {problem && (
            <Hint tone="warn" className="text-[10px]">
              {problem}
            </Hint>
          )}
        </div>
      )}
    </div>
  )
}
