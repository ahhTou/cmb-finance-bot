import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Pause, Play, ScrollText, Square, Trash2, X } from 'lucide-react'
import { type ReactNode, useEffect, useState } from 'react'
import { api } from '../api/client'
import { q, useAction } from '../api/hooks'
import type {
  Mode,
  PlanDisarmRequest,
  PlanItem,
  PlanPauseMode,
  PlanPauseRequest,
  PlanRequest,
  PlanStartRequest,
  PlanView,
  Task,
} from '../api/types'
import { FavoritePicker, LogText } from '../components/shared'
import { Button } from '../components/ui/button'
import { Badge, Hint } from '../components/ui/card'
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
import { ACTIVE_PHASES, cn, parseLocal, toneBg } from '../lib/utils'
import { useUI } from '../store'

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
const pad2 = (value: number) => String(value).padStart(2, '0')

/** True while a watch task is still armed (firing included). */
const activeTask = (task: Task | null | undefined) => !!task && ACTIVE_PHASES.includes(task.phase ?? '')

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
 * Header entry for the plan log, rendered right of 刷新. The log is not a page card
 * any more (2026-11-10): it only opens in a dialog when the user asks for it.
 */
export function PlanLogButton() {
  const { data: view } = useQuery(q.plan)
  const [open, setOpen] = useState(false)
  const lines = view?.logs ?? []
  return (
    <>
      <Button
        data-testid="plan-log-open"
        size="icon"
        className="ml-2 size-[34px] rounded-lg"
        aria-label="计划日志"
        title="计划日志"
        onClick={() => setOpen(true)}
      >
        <ScrollText className="size-4" />
      </Button>
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title="计划日志"
        subtitle={view?.log_path ?? 'var/night/plan.log'}
        width={720}
        height={480}
      >
        <div className="flex min-h-0 flex-1 flex-col gap-2">
          <span className="text-[10px] text-muted">最近 {lines.length} 行</span>
          <LogText lines={lines} className="min-h-0 flex-1 rounded-xl bg-field p-3" />
        </div>
      </Dialog>
    </>
  )
}

/** Big circular icon action in the compact bottom status strip. */
function RoundAction({
  testId,
  label,
  variant = 'default',
  disabled,
  onClick,
  children,
}: {
  testId: string
  label: string
  variant?: 'default' | 'primary'
  disabled?: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <Button
      data-testid={testId}
      variant={variant}
      size="icon"
      className="size-[40px] rounded-full"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </Button>
  )
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
  /** Which pause/stop dialog is open; null when closed. */
  const [control, setControl] = useState<'pause' | 'disarm' | null>(null)

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
  /** The armed item belongs to this plan (so pausing/stopping has two flavours). */
  const ownTask = activeTask(view?.task) && !!plan?.plan_id && view?.task?.plan_id === plan.plan_id
  const terminal =
    !!plan && !running && !stale && (phase === 'done' || phase === 'aborted' || phase === 'disarmed')
  const resultView = terminal && !editingTerminal
  // Paused plans are still a live plan: keep the list read-only until they resume or stop.
  const readOnly = running || phase === 'paused' || stale || resultView
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

  /** Starts a freshly saved dry-run plan directly; real plans use the existing confirm dialog. */
  async function autoBegin(result: PlanView) {
    const saved = result.plan
    if (!saved?.plan_id || !saved.content_revision || !result.settings_revision) return
    const body: PlanStartRequest = {
      plan_id: saved.plan_id,
      content_revision: saved.content_revision,
      settings_revision: result.settings_revision,
      confirm_real_payment: false,
    }
    const started = await run('开始演练计划', () => api<PlanView>('POST', '/api/plan/start', body))
    if (!started) await qc.invalidateQueries({ queryKey: q.plan.queryKey })
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
    const result = await run('保存计划', () => api<PlanView>('PUT', '/api/plan', body))
    const saved = result?.plan
    if (!saved) return
    if (saved.phase !== 'idle') return
    if (activeTask(result.task) && result.task?.plan_id !== saved.plan_id) {
      useUI.getState().setMessage('当前有手动布防，请在布防结束后开始计划。')
      return
    }
    // Auto-start only a runnable plan; an empty or blocked plan stays in the editor.
    if (saved.items.length === 0 || result.problems.length > 0) return
    if (saved.dry_run) {
      await autoBegin(result)
      return
    }
    // Real plans keep the checkbox + confirm click; never bypass the payment confirmation.
    setConfirmation(structuredClone(result))
    setConfirmed(false)
    setConfirming(true)
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

  async function pause(mode: PlanPauseMode) {
    const body: PlanPauseRequest = { mode }
    await run('暂停计划', () => api<PlanView>('POST', '/api/plan/pause', body))
  }

  async function resume() {
    await run('继续计划', () => api<PlanView>('POST', '/api/plan/resume'))
  }

  async function disarm(mode: PlanPauseMode = 'immediate') {
    const body: PlanDisarmRequest = { mode }
    await run('停止计划', () => api<PlanView>('POST', '/api/plan/disarm', body))
  }

  /** No armed item: pausing/stopping applies at once, no extra dialog. */
  function askPause() {
    if (!view || busy) return
    if (ownTask) setControl('pause')
    else void pause('after_current')
  }

  function askDisarm() {
    if (!view || busy) return
    if (ownTask) setControl('disarm')
    else void disarm('immediate')
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

  const nextText = next
    ? `${running ? '当前项' : '下一项'} ${next.code} · ${countdownText(next.at, now)}`
    : ''
  const summaryText = status?.description
    ? nextText
      ? `${status.description} · ${nextText}`
      : status.description
    : nextText || (plan ? '没有待执行的布防' : '还没有计划')
  const heartbeatText =
    view?.heartbeat_age_s != null
      ? `${view.heartbeat_age_s} 秒前`
      : plan?.last_tick
        ? isoClock(plan.last_tick)
        : '—'

  if (!view) {
    return (
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-[26px]">
        <section className="flex min-h-0 flex-1 items-center justify-center rounded-[14px] bg-card">
          {error ? <Hint tone="warn">{error.message}</Hint> : <Hint>正在读取计划…</Hint>}
        </section>
      </div>
    )
  }

  return (
    <div data-testid="plan-page" className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden px-[26px]">
      <section
        data-testid="plan-view"
        className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-hidden rounded-[14px] bg-card px-4 py-3"
      >
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <div className="w-[190px]">
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
          <div className="ml-auto flex shrink-0 items-center gap-2">
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
          </div>
        </div>

        {rows.length === 0 ? (
          <p className="flex min-h-0 flex-1 items-center justify-center text-center text-muted text-xs">
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

        {viewMode === 'timeline' && !readOnly && (
          <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2">
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
          </div>
        )}
        {!readOnly && localProblems.length > 0 && <Hint tone="warn">{localProblems[0]}</Hint>}
      </section>

      {blockingProblems.length > 0 && (
        <section
          data-testid="plan-problems"
          className="flex shrink-0 flex-col gap-1 rounded-[14px] bg-card px-4 py-2.5"
        >
          <p className="font-semibold text-[11px] text-warn">还不能开始</p>
          {blockingProblems.map((problem) => (
            <p key={problem} className="text-[10px] leading-snug text-warn/90">
              {problem}
            </p>
          ))}
          <Hint className="text-[10px]">按上面的提示修改购买时间后，再点「保存计划」。</Hint>
        </section>
      )}

      <section
        data-testid="plan-status-card"
        className="flex shrink-0 flex-col gap-1.5 rounded-[14px] bg-card px-4 py-2.5"
      >
        <div className="flex items-center gap-4">
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <div className="flex min-w-0 items-center gap-2">
              <span data-testid="plan-status" className="flex shrink-0 flex-wrap items-center gap-2">
                <Badge tone={statusPrimaryTone(status)}>{statusPrimaryName(status)}</Badge>
                {secondary && <Badge tone="muted">{secondary}</Badge>}
                {plan && (
                  <Badge tone={plan.dry_run ? 'purple' : 'accent'}>
                    {plan.dry_run ? '演练计划' : '真实计划'}
                  </Badge>
                )}
              </span>
              <span className="min-w-0 truncate text-[11px] text-muted" title={summaryText}>
                {summaryText}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px] text-muted tabular-nums">
              <span>布防 {totals.count} 项</span>
              <span>合计 ¥ {totals.amount}</span>
              <span>
                进度 {finished} / {plan?.items.length ?? 0}
              </span>
              <span className={cn(heartbeatStale && 'text-warn')}>心跳 {heartbeatText}</span>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2.5">
            {running && (
              <RoundAction
                testId="plan-pause"
                label="暂停计划"
                disabled={busy || plan?.pause_requested === true}
                onClick={askPause}
              >
                <Pause className="size-[18px]" />
              </RoundAction>
            )}
            {phase === 'paused' && !stale && (
              <RoundAction
                testId="plan-resume"
                label="继续计划"
                variant="primary"
                disabled={busy}
                onClick={resume}
              >
                <Play className="size-[18px]" />
              </RoundAction>
            )}
            {(running || stale || phase === 'paused') && (
              <RoundAction
                testId="plan-disarm"
                label="停止计划"
                variant="primary"
                disabled={busy || plan?.stop_requested === true}
                onClick={askDisarm}
              >
                <Square className="size-4" />
              </RoundAction>
            )}
            {!running && !stale && phase !== 'paused' && plan && (
              <RoundAction testId="plan-clear" label="清空计划" disabled={busy} onClick={clear}>
                <Trash2 className="size-4" />
              </RoundAction>
            )}
            {!running && !stale && phase === 'idle' && (
              <RoundAction
                testId="plan-start"
                label="开始计划"
                variant="primary"
                disabled={!canStart}
                onClick={openConfirm}
              >
                <Play className="size-[18px]" />
              </RoundAction>
            )}
          </div>
        </div>
        {stale && (
          <Hint tone="warn">计划进程已退出，但计划仍标记为运行中。请点「停止计划」止损后重新保存。</Hint>
        )}
        {!stale && running && (plan?.pause_requested === true || plan?.stop_requested === true) && (
          <Hint>
            {plan?.stop_requested === true
              ? '已请求在当前布防结束后停止计划；这一项结束后不会开始下一项。'
              : '已请求在当前布防结束后暂停；这一项结束后不会开始下一项。'}
          </Hint>
        )}
        {!stale && running && heartbeatStale && (
          <Hint tone="warn">
            计划进程仍在，但
            {view.heartbeat_age_s == null ? '没有心跳记录' : `已 ${view.heartbeat_age_s} 秒没有写心跳`}
            （阈值 {view.heartbeat_timeout_s ?? '—'} 秒）；只提示，不会自动重试交易，可停止计划后检查。
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
      </section>

      <Dialog
        open={control !== null}
        onOpenChange={(open) => !open && setControl(null)}
        title={control === 'pause' ? '暂停计划' : '停止计划'}
        subtitle={
          control === 'pause'
            ? '当前这一项布防还在执行；选择从什么时候开始暂停后续项。'
            : '当前这一项布防还在执行；选择从什么时候开始停止这份计划。'
        }
        width={420}
        dismissable={!busy}
      >
        <div
          data-testid={control === 'pause' ? 'plan-pause-options' : 'plan-disarm-options'}
          className="flex flex-col gap-2"
        >
          {control === 'pause' ? (
            <>
              <Button
                variant="primary"
                disabled={busy}
                onClick={() => {
                  setControl(null)
                  void pause('after_current')
                }}
              >
                在当前布防结束后暂停
              </Button>
              <Button
                disabled={busy}
                onClick={() => {
                  setControl(null)
                  void pause('immediate')
                }}
              >
                停止当前布防并暂停
              </Button>
            </>
          ) : (
            <>
              {phase !== 'paused' && (
                <Button
                  variant="primary"
                  disabled={busy}
                  onClick={() => {
                    setControl(null)
                    void disarm('after_current')
                  }}
                >
                  在当前布防结束后停止
                </Button>
              )}
              <Button
                variant={phase === 'paused' ? 'primary' : 'default'}
                disabled={busy}
                onClick={() => {
                  setControl(null)
                  void disarm('immediate')
                }}
              >
                停止当前布防并停止
              </Button>
            </>
          )}
          <Button variant="ghost" disabled={busy} onClick={() => setControl(null)}>
            算了，我点错了
          </Button>
        </div>
        <Hint className="text-[10px]">
          暂停或停止只影响这份计划，不会改动已经发生的交易；结果以银行交易记录为准。
        </Hint>
      </Dialog>

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
      className="no-scrollbar relative flex min-h-0 flex-1 flex-col overflow-y-auto pl-5 pr-1"
    >
      <div className="relative flex flex-col gap-3">
        <span aria-hidden className="absolute top-1 bottom-1 left-[-13px] w-px bg-white/10" />
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
    <div data-testid="plan-week" className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden">
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
      <div className="grid min-h-0 flex-1 grid-cols-7 gap-1.5 overflow-hidden">
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
          {saved?.state === 'running' && itemStatus(saved, now)?.description && (
            <span className="text-[10px] text-muted">{itemStatus(saved, now)?.description}</span>
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
