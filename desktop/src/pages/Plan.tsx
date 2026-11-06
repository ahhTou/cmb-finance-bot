import { useQuery, useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { q, useAction } from '../api/hooks'
import type { Mode, PlanRequest, PlanStartRequest, PlanView } from '../api/types'
import { FavoritePicker, LogText } from '../components/shared'
import { Button } from '../components/ui/button'
import { Badge, Card, Hint, Metric, MetricGrid } from '../components/ui/card'
import { Dialog } from '../components/ui/dialog'
import { Checkbox, Field, Input, Select, Switch } from '../components/ui/form'
import {
  countdownText,
  draftFromPlan,
  draftItemProblem,
  draftProblems,
  emptyDraftItem,
  isoClock,
  itemInputToISO,
  itemStateName,
  itemStateTone,
  nextItem,
  PLAN_MAX_ITEMS,
  type PlanDraftItem,
  planDirty,
  planPhaseName,
  planPhaseTone,
  planTotals,
} from '../lib/plan'
import { useUI } from '../store'

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
  const [now, setNow] = useState(() => new Date())

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
  const phase = plan?.phase ?? null
  const readOnly = running || stale
  const problems = view?.problems ?? []
  const warnings = view?.warnings ?? []
  const totals = planTotals(plan)
  const next = nextItem(plan)
  const rows = readOnly ? draftFromPlan(plan) : (draft ?? [])
  const localProblems = readOnly ? [] : draftProblems(draft ?? [])
  const dirty = readOnly ? false : planDirty(draft ?? [], dryRun, plan)
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
    setConfirmed(false)
    setConfirming(true)
  }

  async function startNow() {
    const body: PlanStartRequest = { confirm_real_payment: !dryRun && confirmed }
    const result = await run(dryRun ? '开始演练计划' : '开始真实计划', () =>
      api<PlanView>('POST', '/api/plan/start', body),
    )
    if (result) setConfirming(false)
  }

  async function disarm() {
    await run('取消计划', () => api<PlanView>('POST', '/api/plan/disarm'))
  }

  async function clear() {
    await run('清空计划', () => api<PlanView>('DELETE', '/api/plan'))
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
            : '只填购买时间；保存后程序算出每项的冷启动与预计结束时间。'
        }
      >
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <div data-testid="plan-status" className="flex flex-wrap items-center gap-2">
            <Badge tone={planPhaseTone(phase)}>{planPhaseName(phase)}</Badge>
            {plan && (
              <Badge tone={plan.dry_run ? 'purple' : 'accent'}>
                {plan.dry_run ? '演练计划' : '真实计划'}
              </Badge>
            )}
            {stale && <Badge tone="warn">进程已退出</Badge>}
          </div>
          <span className="text-[11px] text-muted">
            {next
              ? `${running ? '当前项' : '下一项'} ${next.code} · ${countdownText(next.at, now)}`
              : plan
                ? (plan.result ?? '没有待执行的布防')
                : '还没有计划'}
          </span>
          <div className="ml-auto flex items-center gap-2">
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
          <Metric title="最近心跳" value={plan?.last_tick ? isoClock(plan.last_tick) : '—'} />
        </MetricGrid>
        {stale && (
          <Hint tone="warn">计划进程已退出，但计划仍标记为运行中。请点「取消计划」止损后重新保存。</Hint>
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
        title="布防列表"
        subtitle={`最多 ${PLAN_MAX_ITEMS} 项；程序严格按购买时间先后串行执行，一项结束后才开始下一项。`}
        badge={
          <Button
            data-testid="plan-add"
            size="compact"
            disabled={readOnly || busy || rows.length >= PLAN_MAX_ITEMS}
            onClick={add}
          >
            添加布防
          </Button>
        }
      >
        {rows.length === 0 ? (
          <p className="text-muted text-xs">
            {plan
              ? '这份计划还没有布防项。点「添加布防」添加第一项。'
              : '还没有计划。点「添加布防」填好购买时间，保存后即可开始。'}
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {rows.map((row, index) => (
              <PlanRow
                key={row.key}
                index={index}
                row={row}
                readOnly={readOnly}
                busy={busy}
                onPatch={patch}
                onRemove={remove}
              />
            ))}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {readOnly ? (
            <Hint>运行中不能修改；需要调整请先取消计划。</Hint>
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
        title={dryRun ? '开始演练计划' : '开始真实计划'}
        subtitle={dryRun ? '演练只输密码，不点确定、不提交。' : '每项到点会按填写金额实际付款。'}
        width={480}
        dismissable={!busy}
      >
        <div data-testid="plan-confirm" className="flex flex-col gap-3.5">
          <div className="flex flex-col gap-2 rounded-xl bg-field px-4 py-3">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted">布防项</span>
              <span className="font-semibold">{totals.count} 项</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-muted">{dryRun ? '演练合计金额' : '真实支付合计'}</span>
              <span className="font-rounded font-semibold text-[22px]">¥ {totals.amount}</span>
            </div>
          </div>
          {next && (
            <p className="text-[11px] text-muted">
              第一项 {next.code} · 购买时间 {isoClock(next.at)}；之后按时间顺序串行执行。
            </p>
          )}
          {!dryRun && (
            <Checkbox
              testId="plan-confirm-check"
              checked={confirmed}
              onChange={setConfirmed}
              label={`我已核对产品和金额，确认真实支付 ¥${totals.amount}`}
            />
          )}
          <div className="flex justify-end gap-2.5">
            <Button disabled={busy} onClick={() => setConfirming(false)}>
              返回
            </Button>
            <Button variant="primary" disabled={busy || (!dryRun && !confirmed)} onClick={startNow}>
              {dryRun ? '开始演练' : '确认真实支付'}
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  )
}

function PlanRow({
  index,
  row,
  readOnly,
  busy,
  onPatch,
  onRemove,
}: {
  index: number
  row: PlanDraftItem
  readOnly: boolean
  busy: boolean
  onPatch: (index: number, changes: Partial<PlanDraftItem>) => void
  onRemove: (index: number) => void
}) {
  const saved = row.saved
  const touched = row.code.trim() !== '' || row.amount.trim() !== '' || row.at !== ''
  const problem = !readOnly && touched ? draftItemProblem(row) : null
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
              冷启动 {isoClock(saved.prep_at)} · 购买 {isoClock(saved.at)} · 预计结束 {isoClock(saved.end_at)}
            </span>
          )}
          {readOnly && saved && <Badge tone={itemStateTone(saved.state)}>{itemStateName(saved.state)}</Badge>}
          {readOnly && saved?.result && <span className="text-[10px] text-muted">{saved.result}</span>}
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
