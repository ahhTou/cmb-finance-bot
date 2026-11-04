import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { api } from '../api/client'
import { q, useAction } from '../api/hooks'
import type { ArmRequest, Mode } from '../api/types'
import { amountSchema, codeSchema, inputDateTime, localISO } from '../lib/utils'
import { useUI } from '../store'
import { BusyLine, FavoritePicker, Spinner } from './shared'
import { Button } from './ui/button'
import { Hint } from './ui/card'
import { Dialog } from './ui/dialog'
import { Field, Input, Segmented, Select, Switch } from './ui/form'

const QUOTA_TIMES = ['00:15', '09:00', '09:15', '10:15', '11:15']
const PREP_CHOICES = [0, 2, 5, 7]

/** 0 is not "0 minutes before the sale"; arming starts the cold start at once. */
function prepLabel(minutes: number) {
  return minutes === 0 ? '立即' : `${minutes} 分钟`
}

/** The next time today or later at `hhmm` that is after `after`. */
function nextQuota(hhmm: string, after: Date) {
  const [h, m] = hhmm.split(':').map(Number)
  const date = new Date(after)
  date.setHours(h, m, 0, 0)
  if (date <= after) date.setDate(date.getDate() + 1)
  return date
}

function earliestQuota(prep: number) {
  const after = new Date(Date.now() + (prep + 2) * 60_000)
  return QUOTA_TIMES.map((t) => nextQuota(t, after)).sort((a, b) => +a - +b)[0]
}

function defaultDate(mode: Mode) {
  if (mode === 'redemption') return earliestQuota(7)
  const tomorrow = new Date()
  tomorrow.setDate(tomorrow.getDate() + 1)
  tomorrow.setHours(9, 0, 0, 0)
  return tomorrow
}

const hhmm = (date: Date) => inputDateTime(date).slice(11, 16)

const schema = z.object({ code: codeSchema, amount: amountSchema })
type Values = z.infer<typeof schema>

export function ArmDialog({
  open,
  onOpenChange,
  mode = 'first_launch',
  drill = false,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  mode?: Mode
  drill?: boolean
}) {
  return (
    <AnimatePresence>
      {open && (
        <ArmForm key={`${mode}-${drill}`} onClose={() => onOpenChange(false)} mode={mode} drill={drill} />
      )}
    </AnimatePresence>
  )
}

function ArmForm({ onClose, mode, drill }: { onClose: () => void; mode: Mode; drill: boolean }) {
  const action = useAction()
  const busy = useUI((s) => s.busy)
  const setMessage = useUI((s) => s.setMessage)
  const settingsQuery = useQuery({ ...q.settings, staleTime: 0 })
  const settings = settingsQuery.data?.settings ?? {}
  const revision = settingsQuery.data?.settings_revision ?? ''
  const loaded = Boolean(revision)

  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { code: '', amount: '' } })
  const [date, setDate] = useState(() => defaultDate(mode))
  const [timeChoice, setTimeChoice] = useState(() => hhmm(defaultDate(mode)))
  const [prep, setPrep] = useState(7)
  const [dry, setDry] = useState(drill)
  const [now, setNow] = useState(drill)
  const [confirm, setConfirm] = useState(false)
  const [confirmAmount, setConfirmAmount] = useState('')
  const [step, setStep] = useState<string | null>(null)
  const [working, setWorking] = useState(false)

  // Once settings arrive, adopt the stored cold-start lead and the next quota slot after it.
  useEffect(() => {
    if (!settingsQuery.data) return
    const stored = settingsQuery.data.settings.cold_start_minutes ?? 7
    const lead = PREP_CHOICES.includes(stored) ? stored : 7
    setPrep(lead)
    if (mode === 'redemption') {
      const next = earliestQuota(lead)
      setDate(next)
      setTimeChoice(hhmm(next))
    }
  }, [settingsQuery.data, mode])

  useEffect(() => {
    if (settingsQuery.error) setMessage(settingsQuery.error.message)
  }, [settingsQuery.error, setMessage])

  const window = settings.irregular_window_minutes ?? 2
  const configuration =
    (prep === 0 ? '布防后立即冷启动' : `提前 ${prep} 分钟冷启动`) +
    '，登录后进入购买页等待。' +
    (mode === 'redemption'
      ? `首次查询提前 ${settings.irregular_advance_ms ?? 200} ms；无额度后前 ${settings.irregular_burst_seconds ?? 15} 秒间隔 ${settings.irregular_retry_min_ms ?? 250}–${settings.irregular_retry_max_ms ?? 400} ms，${settings.irregular_ramp_seconds ?? 20} 秒起 ${settings.irregular_slow_min_ms ?? 1000}–${settings.irregular_slow_max_ms ?? 2000} ms，${settings.irregular_idle_after_seconds ?? 60} 秒起 ${settings.irregular_idle_min_ms ?? 2500}–${settings.irregular_idle_max_ms ?? 4000} ms，最长 ${window} 分钟。`
      : `首次查询延后 ${settings.first_offset_ms ?? 200} ms；无额度后最多再重试 ${settings.first_max_retries ?? 5} 次。`)

  function pickTime(value: string) {
    setTimeChoice(value)
    if (value !== 'custom') setDate(nextQuota(value, new Date(Date.now() + (prep + 2) * 60_000)))
  }

  function problem() {
    if (now && !dry && !drill) return '立即排练只能使用演练。'
    // prep 0 is the emergency path: the sale may be seconds away or already
    // past, so no minimum lead is enforced here either.
    if (prep > 0 && !now && +date <= Date.now() + (prep + 2) * 60_000) {
      return `${mode === 'redemption' ? '额度放出时间' : '开售时间'}至少要在 ${prep + 2} 分钟之后。`
    }
    return null
  }

  const next = form.handleSubmit(
    () => {
      const issue = problem()
      if (issue) return setMessage(issue)
      setConfirmAmount('')
      setConfirm(true)
    },
    (errors) => setMessage(errors.code?.message ?? errors.amount?.message ?? '请检查输入。'),
  )

  const { code, amount } = form.watch()
  const when = now
    ? '约三分钟后'
    : date.toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  const verb = dry ? '演练到密码页' : '提交一次'
  const summary =
    mode === 'redemption'
      ? `产品 ${code.trim()}，${when} 起 ${window} 分钟窗口内在同一购买页查询，有额度就${verb} ${amount} 元。`
      : `产品 ${code.trim()}，${when} ${verb} ${amount} 元。`

  async function submit() {
    const values = form.getValues()
    const issue = problem()
    if (issue) {
      setMessage(issue)
      setConfirm(false)
      return
    }
    const body: ArmRequest = {
      code: values.code.trim(),
      amount: values.amount,
      at: now ? null : localISO(date),
      now,
      dry_run: dry,
      confirm_real_payment: now && !dry,
      prep_minutes: prep,
      settings_revision: revision,
      mode,
    }
    const label = dry ? '演练布防' : '真实布防'
    const arm = () => action(label, () => api('POST', '/api/arm', body))
    setWorking(true)
    try {
      // If the only problem is a stopped emulator, start it here and arm again.
      setStep(dry ? '正在布防（演练）…' : '正在布防…')
      let ok = await arm()
      if (!ok && useUI.getState().message?.includes('模拟器没有在运行')) {
        setStep('模拟器未运行，正在启动（约 20–40 秒）…')
        if (!(await action('启动模拟器', () => api('POST', '/api/emulator/start')))) return
        setStep('模拟器已启动，正在重新布防…')
        ok = await arm()
      }
      if (ok) onClose()
    } finally {
      setStep(null)
      setWorking(false)
    }
  }

  const locked = busy || working
  return (
    <Dialog
      open
      onOpenChange={(value) => !value && onClose()}
      dismissable={!locked}
      title={
        confirm ? '确认布防' : drill ? '演练布防' : `新建${mode === 'redemption' ? '不定时抢购' : ''}布防`
      }
      subtitle={
        confirm
          ? '最后核对一次'
          : mode === 'redemption'
            ? '不定时抢购模式 · 有额度才提交，一笔只提交一次'
            : '首发模式 · 一笔只提交一次'
      }
      width={520}
    >
      <AnimatePresence mode="wait" initial={false}>
        {confirm ? (
          <motion.div
            key="confirm"
            initial={{ opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 24 }}
            transition={{ duration: 0.18 }}
            className="flex flex-col gap-4"
          >
            <p className="selectable text-[13px] leading-relaxed">
              {summary}
              <br />
              {configuration}
            </p>
            {!dry && (
              <Field label="再输入一次金额">
                <Input
                  data-testid="confirm-amount"
                  value={confirmAmount}
                  onChange={(e) => setConfirmAmount(e.target.value)}
                  placeholder="金额"
                />
              </Field>
            )}
            <Hint>一笔只提交一次；结果以银行交易记录为准。提交后不再重试。</Hint>
            {locked && <BusyLine text={step} />}
            <div className="flex justify-end gap-2.5">
              <Button
                disabled={locked}
                onClick={() => {
                  setConfirm(false)
                  setMessage(null)
                }}
              >
                返回
              </Button>
              <Button
                variant="primary"
                disabled={locked || (!dry && confirmAmount !== amount)}
                onClick={submit}
              >
                {locked && <Spinner className="text-white" />}
                {dry ? '开始演练' : '确认真实布防'}
              </Button>
            </div>
          </motion.div>
        ) : (
          <motion.form
            key="form"
            initial={{ opacity: 0, x: -24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -24 }}
            transition={{ duration: 0.18 }}
            onSubmit={next}
            className="flex flex-col gap-4"
          >
            <div className="flex gap-3.5">
              <Field label="产品代码">
                <Input placeholder="如 JX040229" autoFocus {...form.register('code')} />
              </Field>
              <Field label="购买金额">
                <Input placeholder="上限 50000 元" inputMode="decimal" {...form.register('amount')} />
              </Field>
            </div>
            <FavoritePicker onPick={(value) => form.setValue('code', value)} />
            {mode === 'redemption' ? (
              <>
                <div className="flex items-center gap-3">
                  <span className="text-[13px]">开始盯盘时间</span>
                  <Select value={timeChoice} disabled={now} onChange={(e) => pickTime(e.target.value)}>
                    {QUOTA_TIMES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                    <option value="custom">自定义</option>
                  </Select>
                  {timeChoice === 'custom' ? (
                    <Input
                      type="datetime-local"
                      className="h-[34px] w-auto"
                      disabled={now}
                      value={inputDateTime(date)}
                      onChange={(e) => e.target.value && setDate(new Date(e.target.value))}
                    />
                  ) : (
                    <span className="text-[11px] text-muted">
                      {date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', weekday: 'short' })}
                    </span>
                  )}
                </div>
                <Hint>每天这些时间左右可能放出额度，不保证准时；其他日期和时间请选择自定义。</Hint>
              </>
            ) : (
              <div className="flex items-center justify-between gap-3">
                <span className="text-[13px]">开售时间</span>
                <Input
                  type="datetime-local"
                  className="h-[34px] w-auto"
                  disabled={now}
                  value={inputDateTime(date)}
                  onChange={(e) => e.target.value && setDate(new Date(e.target.value))}
                />
              </div>
            )}
            <div className="flex flex-col gap-2">
              <div className="flex justify-between">
                <span className="text-[11px] text-muted">冷启动提前量</span>
                <span className="font-semibold text-[11px]">{prepLabel(prep)}</span>
              </div>
              <Segmented
                label="冷启动提前量"
                value={prep}
                onChange={setPrep}
                options={PREP_CHOICES.map((value) => ({ value, label: prepLabel(value) }))}
              />
              <Hint>
                {prep === 0
                  ? '立即：布防后马上冷启动、登录并进入购买页，再等到开售时间。'
                  : '测试可用 2 分钟；正式布防建议 7 分钟。'}
              </Hint>
            </div>
            <div className="flex flex-col gap-[5px]">
              <span className="text-[11px] text-muted">当前配置</span>
              <p className="text-muted text-xs leading-relaxed">{loaded ? configuration : '正在读取设置…'}</p>
            </div>
            {drill ? (
              <>
                <Switch label="实际付款：输入交易密码并提交" checked={!dry} onChange={(v) => setDry(!v)} />
                <Hint tone={dry ? 'muted' : 'warn'} className="text-xs">
                  {dry
                    ? '默认只到密码页，不输入密码、不提交。'
                    : '将按填写金额实际购买一笔，下一步需再次输入金额确认。'}
                </Hint>
              </>
            ) : (
              <Switch
                label="演练：只到密码页，不输入密码、不提交"
                checked={dry}
                onChange={(v) => {
                  setDry(v)
                  if (!v) setNow(false)
                }}
              />
            )}
            <Switch
              label={drill ? '立即开始（约三分钟后购买）' : '立即排练'}
              checked={now}
              disabled={!dry && !drill}
              onChange={setNow}
            />
            {locked && <BusyLine text={step} />}
            <div className="flex justify-end gap-2.5">
              <Button disabled={locked} onClick={onClose}>
                取消
              </Button>
              <Button type="submit" variant="primary" disabled={busy || !loaded}>
                下一步
              </Button>
            </div>
          </motion.form>
        )}
      </AnimatePresence>
    </Dialog>
  )
}
