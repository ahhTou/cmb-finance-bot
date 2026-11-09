import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'motion/react'
import { type ReactNode, useEffect, useState } from 'react'
import { type UseFormRegisterReturn, useForm } from 'react-hook-form'
import { api, isTauri, resetBackend } from '../api/client'
import { q, useAction, useWatch } from '../api/hooks'
import type { PlanSettings, PurchaseSettings, PushConfig, PushTestResult } from '../api/types'
import { PurchaseFlow } from '../components/PurchaseFlow'
import { PushPreferencesCard } from '../components/PushPreferences'
import { Button } from '../components/ui/button'
import { Badge, Card, Hint } from '../components/ui/card'
import { Confirm } from '../components/ui/dialog'
import { Field, Input, Segmented } from '../components/ui/form'
import { cn, type Tone } from '../lib/utils'
import { type BackendConfig, backendConfig, setBackendConfig } from '../platform'
import { useUI } from '../store'

type Tab = 'watch' | 'credentials' | 'push' | 'project' | 'other'
const TABS: { value: Tab; label: string }[] = [
  { value: 'watch', label: '值守配置' },
  { value: 'credentials', label: '凭据' },
  { value: 'push', label: '推送通知' },
  { value: 'project', label: '项目' },
  { value: 'other', label: '其他' },
]

export function SettingsPage() {
  const [tab, setTab] = useState<Tab>('watch')
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-[26px] pb-2">
      <div className="w-full max-w-[420px] shrink-0">
        <Segmented label="设置分类" value={tab} options={TABS} onChange={setTab} />
      </div>
      {tab === 'watch' && <WatchSettings />}
      {tab === 'credentials' && <CredentialSettings />}
      {tab === 'push' && (
        <>
          <PushCard />
          <PushPreferencesCard />
        </>
      )}
      {tab === 'project' && <ProjectCard />}
      {tab === 'other' && <OtherSettings />}
    </div>
  )
}

// ---------------------------------------------------------------- 值守配置

/** Same defaults and limits as src/purchase_settings.py. */
const DEFAULTS = {
  first_offset_ms: 200,
  first_max_retries: 5,
  irregular_advance_ms: 200,
  irregular_window_minutes: 2,
  irregular_burst_seconds: 60,
  irregular_retry_min_ms: 300,
  irregular_retry_max_ms: 500,
  irregular_ramp_seconds: 65,
  irregular_slow_min_ms: 1000,
  irregular_slow_max_ms: 2000,
  irregular_idle_after_seconds: 90,
  irregular_idle_min_ms: 2500,
  irregular_idle_max_ms: 4000,
  reopen_deadline: 60,
  drill_form_deadline: 10,
  password_page_timeout_s: 10,
  keypad_timeout_ms: 1200,
  keypad_stable_ms: 60,
  keypad_stable_samples: 2,
  keypad_sample_gap_ms: 0,
  password_same_digit_gap_ms: 50,
  password_different_digit_gap_ms: 10,
  password_confirm_gap_ms: 150,
  password_confirm_timeout_ms: 600,
  password_retry_gap_ms: 100,
  password_done_gap_ms: 150,
  password_close_wait_ms: 500,
  result_first_wait_ms: 1000,
  result_timeout_s: 20,
}
type Key = keyof typeof DEFAULTS
type Values = Record<Key, string>
const KEYS = Object.keys(DEFAULTS) as Key[]
const LIMITS: Record<Key, [number, number]> = {
  first_offset_ms: [0, 10000],
  first_max_retries: [0, 100],
  irregular_advance_ms: [0, 10000],
  irregular_window_minutes: [1, 60],
  irregular_burst_seconds: [0, 3600],
  irregular_retry_min_ms: [1, 60000],
  irregular_retry_max_ms: [1, 60000],
  irregular_ramp_seconds: [0, 3600],
  irregular_slow_min_ms: [1, 60000],
  irregular_slow_max_ms: [1, 60000],
  irregular_idle_after_seconds: [0, 3600],
  irregular_idle_min_ms: [1, 60000],
  irregular_idle_max_ms: [1, 60000],
  reopen_deadline: [1, 300],
  drill_form_deadline: [1, 300],
  password_page_timeout_s: [1, 120],
  keypad_timeout_ms: [100, 30000],
  keypad_stable_ms: [0, 5000],
  keypad_stable_samples: [2, 20],
  keypad_sample_gap_ms: [0, 1000],
  password_same_digit_gap_ms: [0, 3000],
  password_different_digit_gap_ms: [0, 3000],
  password_confirm_gap_ms: [0, 5000],
  password_confirm_timeout_ms: [0, 30000],
  password_retry_gap_ms: [0, 5000],
  password_done_gap_ms: [0, 5000],
  password_close_wait_ms: [0, 10000],
  result_first_wait_ms: [0, 60000],
  result_timeout_s: [1, 120],
}

function validate(v: Values) {
  const errors: Partial<Record<Key, string>> = {}
  for (const key of KEYS) {
    const [min, max] = LIMITS[key]
    const n = Number(v[key])
    if (!/^\d+$/.test(v[key] ?? '') || n < min || n > max) errors[key] = `请输入 ${min}–${max} 的整数`
  }
  const num = (key: Key) => Number(v[key])
  for (const [lo, hi] of [
    ['irregular_retry_min_ms', 'irregular_retry_max_ms'],
    ['irregular_slow_min_ms', 'irregular_slow_max_ms'],
    ['irregular_idle_min_ms', 'irregular_idle_max_ms'],
  ] as const) {
    if (!errors[lo] && !errors[hi] && num(lo) > num(hi)) errors[hi] = '间隔上限不能小于下限'
  }
  if (!errors.irregular_ramp_seconds && num('irregular_burst_seconds') > num('irregular_ramp_seconds'))
    errors.irregular_ramp_seconds = '过渡结束不能早于高频结束'
  if (
    !errors.irregular_idle_after_seconds &&
    num('irregular_ramp_seconds') > num('irregular_idle_after_seconds')
  )
    errors.irregular_idle_after_seconds = '降频结束不能早于过渡结束'
  if (
    !errors.keypad_timeout_ms &&
    !errors.keypad_stable_ms &&
    num('keypad_stable_ms') >= num('keypad_timeout_ms')
  )
    errors.keypad_stable_ms = '稳定时长必须小于等键盘上限，否则永远等不到就绪'
  return errors
}

const toValues = (source: Partial<Record<string, unknown>>) =>
  Object.fromEntries(KEYS.map((key) => [key, String(source[key] ?? DEFAULTS[key])])) as Values

function WatchSettings() {
  const busy = useUI((s) => s.busy)
  const action = useAction()
  const qc = useQueryClient()
  const { data } = useQuery({ ...q.settings, staleTime: 0 })
  const [saved, setSaved] = useState(false)
  const form = useForm<Values>({ mode: 'onChange' })
  const values = form.watch()
  const errors = validate(values)
  const invalid = Object.keys(errors).length > 0
  const dirty = form.formState.isDirty
  const disabled = !data || busy

  useEffect(() => {
    if (data) form.reset(toValues(data.settings))
  }, [data, form])

  const save = form.handleSubmit(async (raw) => {
    const body = Object.fromEntries(KEYS.map((key) => [key, Number(raw[key])]))
    const result = await action('保存值守配置', () => api<PurchaseSettings>('PUT', '/api/settings', body))
    if (result) {
      qc.setQueryData(q.settings.queryKey, result)
      form.reset(toValues(result.settings))
      setSaved(true)
    }
  })

  const num = (key: Key, unit: string, label: string) => (
    <NumberInput
      label={label}
      unit={unit}
      error={errors[key]}
      disabled={disabled}
      placeholder={String(DEFAULTS[key])}
      {...form.register(key, { onChange: () => setSaved(false) })}
    />
  )

  // Same binding as `num`, 26px tall so it fits inside a flow node.
  const field = (key: string, unit: string, label: string) => (
    <NumberInput
      compact
      label={label}
      unit={unit}
      error={errors[key as Key]}
      disabled={disabled}
      placeholder={String(DEFAULTS[key as Key])}
      {...form.register(key as Key, { onChange: () => setSaved(false) })}
    />
  )

  return (
    <form className="flex flex-col gap-4" onSubmit={save}>
      <Card title="首发模式" subtitle="开售时间一到就查询；没有额度时立即重试，次数用完就停。">
        <div className="grid grid-cols-2 gap-4">
          <Setting label="首次查询延后" help="开售后多久发出第一次查询" error={errors.first_offset_ms}>
            {num('first_offset_ms', '毫秒', '首次查询延后')}
          </Setting>
          <Setting label="最多重试" help="不含第一次查询" error={errors.first_max_retries}>
            {num('first_max_retries', '次', '最多重试')}
          </Setting>
        </div>
      </Card>

      <Card title="不定时抢购" subtitle="开售前开始查询，在窗口内按下面的节奏反复查，查到额度就提交一次。">
        <div className="grid grid-cols-2 gap-4">
          <Setting label="首次查询提前" help="比设定时间早多久开始查" error={errors.irregular_advance_ms}>
            {num('irregular_advance_ms', '毫秒', '首次查询提前')}
          </Setting>
          <Setting label="查询窗口" help="从第一次查询起，最多查多久" error={errors.irregular_window_minutes}>
            {num('irregular_window_minutes', '分钟', '查询窗口')}
          </Setting>
        </div>
        <Cadence values={values} errors={errors} num={num} />
      </Card>

      <Card title="单笔购买" subtitle="手动发起的单笔购买，购买页打不开时最多重试多久。">
        <div className="grid grid-cols-2 gap-4">
          <Setting label="直接购买总时限" error={errors.reopen_deadline}>
            {num('reopen_deadline', '秒', '直接购买总时限')}
          </Setting>
          <Setting label="演练总时限" error={errors.drill_form_deadline}>
            {num('drill_form_deadline', '秒', '演练总时限')}
          </Setting>
        </div>
      </Card>

      <Card
        title="购买时序配置"
        badge={<Badge>限度 5 · 固定 7</Badge>}
        subtitle="从有额度到结果页的真实执行顺序。竖线是主干，向右分叉的是另一条走向，末端写明是汇回某一步还是终止；每个值都落在它生效的那一步，并标明「等不到才生效」还是「固定停顿」。"
      >
        <PurchaseFlow field={field} errors={errors} limits={LIMITS} />
      </Card>

      <div className="sticky bottom-0 flex items-center gap-3 rounded-[14px] bg-card/95 px-[18px] py-3 shadow-[0_-8px_24px_rgb(0_0_0/0.35)] ring-[0.6px] ring-white/10 backdrop-blur">
        <span className={cn('text-xs', invalid ? 'text-accent' : 'text-muted')}>
          {invalid
            ? `有 ${Object.keys(errors).length} 项需要修改`
            : dirty
              ? '有未保存的修改'
              : saved
                ? '已保存，之后的新布防使用这套配置'
                : '新布防使用这套配置；已布防的任务保持原值'}
        </span>
        <span className="flex-1" />
        <Button
          variant="ghost"
          disabled={disabled}
          onClick={() => {
            for (const key of KEYS)
              form.setValue(key, String(DEFAULTS[key]), { shouldDirty: true, shouldValidate: true })
            setSaved(false)
          }}
        >
          恢复默认
        </Button>
        <Button
          variant="ghost"
          disabled={disabled || !dirty}
          onClick={() => data && form.reset(toValues(data.settings))}
        >
          撤销修改
        </Button>
        <Button type="submit" variant="primary" disabled={disabled || invalid || !dirty}>
          保存值守配置
        </Button>
      </div>
    </form>
  )
}

const TIERS = [
  { name: '高频', color: 'bg-accent' },
  { name: '过渡', color: 'bg-gradient-to-r from-accent to-warn' },
  { name: '降频', color: 'bg-warn' },
  { name: '低频', color: 'bg-blue' },
]

/** The redemption backoff as four tiers in order, with a timeline over the query window. */
function Cadence({
  values,
  errors,
  num,
}: {
  values: Values
  errors: Partial<Record<Key, string>>
  num: (key: Key, unit: string, label: string) => ReactNode
}) {
  const n = (key: Key) => Number(values[key]) || 0
  const window = n('irregular_window_minutes') * 60
  const ends = [
    n('irregular_burst_seconds'),
    n('irregular_ramp_seconds'),
    n('irregular_idle_after_seconds'),
    window,
  ]
  const avg = (lo: Key, hi: Key) => (n(lo) + n(hi)) / 2
  const intervals = [
    avg('irregular_retry_min_ms', 'irregular_retry_max_ms'),
    (avg('irregular_retry_min_ms', 'irregular_retry_max_ms') +
      avg('irregular_slow_min_ms', 'irregular_slow_max_ms')) /
      2,
    avg('irregular_slow_min_ms', 'irregular_slow_max_ms'),
    avg('irregular_idle_min_ms', 'irregular_idle_max_ms'),
  ]
  // Clip every tier to the window: tiers that start after it never run.
  let from = 0
  const spans = ends.map((end, i) => {
    const start = Math.min(from, window)
    const stop = Math.min(Math.max(end, from), window)
    from = Math.max(end, from)
    return { start, stop, count: intervals[i] > 0 ? ((stop - start) * 1000) / intervals[i] : 0 }
  })
  const total = Math.round(spans.reduce((sum, s) => sum + s.count, 0))
  const cadenceErrors = (
    [
      'irregular_burst_seconds',
      'irregular_retry_min_ms',
      'irregular_retry_max_ms',
      'irregular_ramp_seconds',
      'irregular_slow_min_ms',
      'irregular_slow_max_ms',
      'irregular_idle_after_seconds',
      'irregular_idle_min_ms',
      'irregular_idle_max_ms',
    ] as const
  )
    .map((key) => errors[key])
    .filter(Boolean)

  const range = (lo: Key, hi: Key, name: string) => (
    <div className="flex items-center gap-2">
      <div className="w-[118px]">{num(lo, '毫秒', `${name}间隔下限`)}</div>
      <span className="text-muted text-xs">~</span>
      <div className="w-[118px]">{num(hi, '毫秒', `${name}间隔上限`)}</div>
    </div>
  )
  const endInput = (key: Key, name: string) => (
    <div className="w-[104px]">{num(key, '秒', `${name}结束`)}</div>
  )

  const rows: [ReactNode, ReactNode][] = [
    [
      <TimeSpan key="t" start="0 秒" end={endInput('irregular_burst_seconds', '高频')} />,
      range('irregular_retry_min_ms', 'irregular_retry_max_ms', '高频'),
    ],
    [
      <TimeSpan
        key="t"
        start={`${n('irregular_burst_seconds')} 秒`}
        end={endInput('irregular_ramp_seconds', '过渡')}
      />,
      <span key="i" className="text-muted text-xs">
        从高频间隔逐渐放慢到降频间隔
      </span>,
    ],
    [
      <TimeSpan
        key="t"
        start={`${n('irregular_ramp_seconds')} 秒`}
        end={endInput('irregular_idle_after_seconds', '降频')}
      />,
      range('irregular_slow_min_ms', 'irregular_slow_max_ms', '降频'),
    ],
    [
      <TimeSpan key="t" start={`${n('irregular_idle_after_seconds')} 秒`} end="窗口结束" />,
      range('irregular_idle_min_ms', 'irregular_idle_max_ms', '低频'),
    ],
  ]

  return (
    <div className="flex flex-col gap-3 rounded-xl bg-field/60 p-3.5">
      <div className="flex items-baseline gap-2">
        <h3 className="font-semibold text-[13px]">查询节奏</h3>
        <span className="text-[11px] text-muted">时间从第一次查询算起；每段在区间内随机等待</span>
        <span className="flex-1" />
        <span className="text-[11px] text-muted">
          {window > 0 ? `${window} 秒窗口内最多约 ${total} 次查询（不计请求耗时）` : ''}
        </span>
      </div>

      <Timeline spans={spans} window={window} />

      <div className="grid grid-cols-[64px_auto_1fr] items-center gap-x-4 gap-y-2.5">
        <span className="text-[10px] text-muted">阶段</span>
        <span className="text-[10px] text-muted">时间段</span>
        <span className="text-[10px] text-muted">查询间隔</span>
        {rows.map(([time, interval], i) => (
          <Row key={TIERS[i].name} tier={TIERS[i]} skipped={window > 0 && spans[i].stop <= spans[i].start}>
            {time}
            {interval}
          </Row>
        ))}
      </div>
      {cadenceErrors.length > 0 && <Hint tone="accent">{[...new Set(cadenceErrors)].join('；')}</Hint>}
    </div>
  )
}

function Row({
  tier,
  skipped,
  children,
}: {
  tier: (typeof TIERS)[number]
  skipped: boolean
  children: [ReactNode, ReactNode]
}) {
  return (
    <>
      <span className={cn('flex items-center gap-2 font-medium text-xs', skipped && 'opacity-45')}>
        <span className={cn('size-2 rounded-full', tier.color)} />
        {tier.name}
      </span>
      <div className={cn(skipped && 'opacity-45')}>{children[0]}</div>
      <div className={cn('flex items-center gap-2', skipped && 'opacity-45')}>
        {children[1]}
        {skipped && <Badge>窗口内不会进入</Badge>}
      </div>
    </>
  )
}

function TimeSpan({ start, end }: { start: string; end: ReactNode }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-[44px] text-right text-muted tabular-nums">{start}</span>
      <span className="text-muted">→</span>
      {typeof end === 'string' ? <span className="text-muted">{end}</span> : end}
    </div>
  )
}

function Timeline({ spans, window }: { spans: { start: number; stop: number }[]; window: number }) {
  if (window <= 0) return null
  const marks = [...new Set([0, ...spans.map((s) => s.stop)])].filter((t) => t <= window)
  // Drop a label that would sit on top of the previous one.
  const shown = marks.filter((t, i) => i === 0 || t === window || (t - marks[i - 1]) / window > 0.07)
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex h-2.5 overflow-hidden rounded-full bg-button">
        {spans.map((s, i) =>
          s.stop > s.start ? (
            <motion.div
              key={TIERS[i].name}
              layout
              transition={{ type: 'spring', stiffness: 400, damping: 40 }}
              className={cn('h-full', TIERS[i].color)}
              style={{ width: `${((s.stop - s.start) / window) * 100}%` }}
              title={`${TIERS[i].name} ${s.start}–${s.stop} 秒`}
            />
          ) : null,
        )}
      </div>
      <div className="relative h-3.5 text-[10px] text-muted tabular-nums">
        {shown.map((t) => (
          <span
            key={t}
            className="absolute"
            style={
              t === window
                ? { right: 0 }
                : t === 0
                  ? { left: 0 }
                  : { left: `${(t / window) * 100}%`, transform: 'translateX(-50%)' }
            }
          >
            {t} 秒
          </span>
        ))}
      </div>
    </div>
  )
}

/** A "?" that explains one value on hover or keyboard focus. */
function Setting({
  label,
  help,
  error,
  kind,
  children,
}: {
  label: string
  help?: string
  error?: string
  kind?: 'limit' | 'fixed'
  children: ReactNode
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <span className="flex items-center gap-2 font-medium text-xs">
        {label}
        {kind && (
          <Badge tone={kind === 'limit' ? 'warn' : 'blue'}>{kind === 'limit' ? '限度' : '固定'}</Badge>
        )}
      </span>
      {children}
      {error ? <Hint tone="accent">{error}</Hint> : help ? <Hint>{help}</Hint> : null}
    </div>
  )
}

/** One stage of the password flow: a caption line over a two-column grid. */

function NumberInput({
  unit,
  label,
  error,
  disabled,
  placeholder,
  compact,
  ...register
}: UseFormRegisterReturn & {
  unit: string
  label: string
  error?: string
  disabled?: boolean
  placeholder?: string
  /** 26px variant for the flow diagram, where vertical space is fixed. */
  compact?: boolean
}) {
  return (
    <div
      className={cn(
        'flex items-center rounded-lg bg-field pr-2.5 focus-within:ring-2 focus-within:ring-accent/50',
        compact ? 'h-[26px] rounded-md pr-2' : 'h-[34px]',
        error && 'ring-1 ring-accent',
        disabled && 'opacity-50',
      )}
    >
      <input
        aria-label={label}
        aria-invalid={!!error}
        inputMode="numeric"
        autoComplete="off"
        disabled={disabled}
        placeholder={placeholder}
        className={cn(
          'h-full w-full min-w-0 bg-transparent text-fg tabular-nums outline-none placeholder:text-muted/60',
          compact ? 'pl-2 text-[11px]' : 'pl-3 text-[13px]',
        )}
        {...register}
      />
      <span className={cn('shrink-0 text-muted', compact ? 'text-[10px]' : 'text-[11px]')}>{unit}</span>
    </div>
  )
}

// ---------------------------------------------------------------- 其他

/** Same defaults and limits as src/plan_settings.py. */
const OTHER_DEFAULTS = {
  arm_gap_minutes: 2,
  first_end_slack_minutes: 2,
  end_timeout_minutes: 5,
  grace_seconds: 15,
  poll_seconds: 2,
  heartbeat_seconds: 10,
  kill_wait_seconds: 10,
  heartbeat_timeout_seconds: 60,
  health_timeout_minutes: 15,
}
type OtherKey = keyof typeof OTHER_DEFAULTS
type OtherValues = Record<OtherKey, string>
const OTHER_KEYS = Object.keys(OTHER_DEFAULTS) as OtherKey[]
const OTHER_LIMITS: Record<OtherKey, [number, number]> = {
  arm_gap_minutes: [0, 60],
  first_end_slack_minutes: [0, 60],
  end_timeout_minutes: [1, 120],
  grace_seconds: [0, 300],
  poll_seconds: [1, 60],
  heartbeat_seconds: [1, 300],
  kill_wait_seconds: [1, 120],
  heartbeat_timeout_seconds: [10, 600],
  health_timeout_minutes: [1, 60],
}
const OTHER_META: Record<OtherKey, { label: string; unit: string; kind: 'limit' | 'fixed'; help: string }> = {
  arm_gap_minutes: {
    label: '相邻项间隔',
    unit: '分钟',
    kind: 'limit',
    help: '下一项冷启动至少比上一项预计结束晚这么久；只参与排程校验，不产生等待。',
  },
  first_end_slack_minutes: {
    label: '首发结束余量',
    unit: '分钟',
    kind: 'limit',
    help: '首发项在查询窗口之后额外预留的提交余量；只影响排程估算。',
  },
  end_timeout_minutes: {
    label: '单项超时',
    unit: '分钟',
    kind: 'limit',
    help: '超过预计结束这么久仍未结束就停止；条件成立即停，调大不会固定等待。',
  },
  grace_seconds: {
    label: '进程消失宽限',
    unit: '秒',
    kind: 'limit',
    help: '值守进程消失后等这么久仍无终态才判失败或结果未知；拿到终态就继续。',
  },
  poll_seconds: {
    label: '轮询间隔',
    unit: '秒',
    kind: 'fixed',
    help: '计划进程检查值守状态的固定间隔，直接形成响应延迟。',
  },
  heartbeat_seconds: {
    label: '心跳间隔',
    unit: '秒',
    kind: 'fixed',
    help: '计划进程写 last_tick 的固定间隔；不能短于轮询间隔。',
  },
  heartbeat_timeout_seconds: {
    label: '心跳超时',
    unit: '秒',
    kind: 'limit',
    help: '计划进程超过这么久没有写心跳就标记为心跳异常；只提示，不自动重试交易。',
  },
  kill_wait_seconds: {
    label: '终止等待',
    unit: '秒',
    kind: 'limit',
    help: 'SIGTERM 后等这么久再 SIGKILL；进程提前退出就继续。',
  },
  health_timeout_minutes: {
    label: '健康检查最长等待',
    unit: '分钟',
    kind: 'limit',
    help: '布防前检查模拟器和网络，能修好就继续；成功即继续，不会等满；只有一直修不好才让这一项失败。',
  },
}

function validateOther(v: OtherValues) {
  const errors: Partial<Record<OtherKey, string>> = {}
  for (const key of OTHER_KEYS) {
    const [min, max] = OTHER_LIMITS[key]
    const n = Number(v[key])
    if (!/^\d+$/.test(v[key] ?? '') || n < min || n > max) errors[key] = `请输入 ${min}–${max} 的整数`
  }
  const poll = Number(v.poll_seconds)
  const heartbeat = Number(v.heartbeat_seconds)
  if (!errors.poll_seconds && !errors.heartbeat_seconds && poll > heartbeat)
    errors.heartbeat_seconds = '心跳间隔不能短于轮询间隔'
  return errors
}

const toOtherValues = (source: Partial<Record<string, unknown>>) =>
  Object.fromEntries(
    OTHER_KEYS.map((key) => [key, String(source[key] ?? OTHER_DEFAULTS[key])]),
  ) as OtherValues

function OtherSettings() {
  const busy = useUI((s) => s.busy)
  const action = useAction()
  const qc = useQueryClient()
  const { data } = useQuery({ ...q.planSettings, staleTime: 0 })
  const [saved, setSaved] = useState(false)
  const form = useForm<OtherValues>({ mode: 'onChange' })
  const values = form.watch()
  const errors = validateOther(values)
  const invalid = Object.keys(errors).length > 0
  const dirty = form.formState.isDirty
  const disabled = !data || busy

  useEffect(() => {
    if (data) form.reset(toOtherValues(data.settings))
  }, [data, form])

  const save = form.handleSubmit(async (raw) => {
    const body = Object.fromEntries(OTHER_KEYS.map((key) => [key, Number(raw[key])]))
    const result = await action('保存其他设置', () => api<PlanSettings>('PUT', '/api/settings/other', body))
    if (result) {
      qc.setQueryData(q.planSettings.queryKey, result)
      form.reset(toOtherValues(result.settings))
      setSaved(true)
    }
  })

  const num = (key: OtherKey) => (
    <NumberInput
      label={OTHER_META[key].label}
      unit={OTHER_META[key].unit}
      error={errors[key]}
      disabled={disabled}
      placeholder={String(OTHER_DEFAULTS[key])}
      {...form.register(key, { onChange: () => setSaved(false) })}
    />
  )

  const field = (key: OtherKey) => (
    <Setting
      label={OTHER_META[key].label}
      help={OTHER_META[key].help}
      error={errors[key]}
      kind={OTHER_META[key].kind}
    >
      {num(key)}
    </Setting>
  )

  return (
    <form className="flex flex-col gap-4" onSubmit={save} data-testid="other-settings">
      <Card title="计划排程" subtitle="这些值只影响计划的排程估算和校验，不改变购买参数。">
        <div className="grid grid-cols-2 gap-4">
          {field('arm_gap_minutes')}
          {field('first_end_slack_minutes')}
        </div>
      </Card>

      <Card title="进程监控" subtitle="计划进程检查值守、写心跳和处理异常的时间参数；计划开始时快照。">
        <div className="grid grid-cols-2 gap-4">
          {field('poll_seconds')}
          {field('heartbeat_seconds')}
          {field('grace_seconds')}
          {field('end_timeout_minutes')}
          {field('kill_wait_seconds')}
          {field('heartbeat_timeout_seconds')}
          {field('health_timeout_minutes')}
        </div>
      </Card>

      <div className="sticky bottom-0 flex items-center gap-3 rounded-[14px] bg-card/95 px-[18px] py-3 shadow-[0_-8px_24px_rgb(0_0_0/0.35)] ring-[0.6px] ring-white/10 backdrop-blur">
        <span className={cn('text-xs', invalid ? 'text-accent' : 'text-muted')}>
          {invalid
            ? `有 ${Object.keys(errors).length} 项需要修改`
            : dirty
              ? '有未保存的修改'
              : saved
                ? '已保存，之后的新计划使用这套值'
                : '新计划开始时使用这套值；运行中的计划保持开始时的值'}
        </span>
        <span className="flex-1" />
        <Button
          variant="ghost"
          disabled={disabled}
          onClick={() => {
            for (const key of OTHER_KEYS)
              form.setValue(key, String(OTHER_DEFAULTS[key]), { shouldDirty: true, shouldValidate: true })
            setSaved(false)
          }}
        >
          恢复默认
        </Button>
        <Button
          variant="ghost"
          disabled={disabled || !dirty}
          onClick={() => data && form.reset(toOtherValues(data.settings))}
        >
          撤销修改
        </Button>
        <Button
          type="submit"
          variant="primary"
          disabled={disabled || invalid || !dirty}
          data-testid="other-save"
        >
          保存其他设置
        </Button>
      </div>
    </form>
  )
}

// ---------------------------------------------------------------- 凭据

function CredentialSettings() {
  const w = useWatch()
  const busy = useUI((s) => s.busy)
  const locked = w.credentialsDisabled || busy
  const stored = w.credentialState === '已设置'
  return (
    <>
      <Card title="凭据状态" subtitle="这里只同步脚本保存的值，不会修改银行 App 里的设置。">
        <div className="flex gap-6">
          <Status label="登录与交易凭据" value={w.credentialState} good={stored} />
        </div>
        {w.credentialsDisabled && <Hint tone="warn">值守进行中，暂时不能修改凭据。</Hint>}
      </Card>
      <div className={cn('grid grid-cols-2 gap-4', locked && 'pointer-events-none opacity-60')}>
        <PatternCard />
        <PasswordCard />
      </div>
    </>
  )
}

function Status({ label, value, good }: { label: string; value: unknown; good: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="text-muted text-xs">{label}</span>
      <Badge tone={good ? 'good' : 'warn'}>{typeof value === 'string' ? value : '—'}</Badge>
    </div>
  )
}

// ---------------------------------------------------------------- 项目

/** Project folder and Python. Only the desktop shell starts the backend, so only it can change them. */
function ProjectCard() {
  const qc = useQueryClient()
  const action = useAction()
  const { data: info } = useQuery(q.info)
  const [config, setConfig] = useState<BackendConfig>({ root: '', python: '' })
  useEffect(() => {
    if (isTauri) backendConfig().then(setConfig)
    else if (info) setConfig({ root: info.root, python: info.python })
  }, [info])

  async function save() {
    await action(
      '重启后端',
      async () => {
        setConfig(await setBackendConfig(config))
        resetBackend()
        await qc.invalidateQueries()
      },
      false,
    )
  }

  return (
    <Card title="项目设置" subtitle="项目目录和运行脚本用的 Python 解释器">
      <Field label="项目目录">
        <Input
          value={config.root}
          readOnly={!isTauri}
          placeholder="项目目录绝对路径"
          onChange={(e) => setConfig({ ...config, root: e.target.value })}
        />
      </Field>
      <Field label="Python 路径">
        <Input
          value={config.python}
          readOnly={!isTauri}
          placeholder="Python 绝对路径"
          onChange={(e) => setConfig({ ...config, python: e.target.value })}
        />
      </Field>
      <div className="flex items-center">
        <Hint className="flex-1">
          {isTauri ? '保存后会用新设置重启本地后端。' : '浏览器开发模式下由 pnpm server 决定，这里只读。'}
        </Hint>
        {isTauri && (
          <Button variant="primary" onClick={save}>
            保存设置
          </Button>
        )}
      </div>
    </Card>
  )
}

function PatternCard() {
  const action = useAction()
  const [pattern, setPattern] = useState('')
  const [repeated, setRepeated] = useState('')
  const [second, setSecond] = useState(false)
  const current = second ? repeated : pattern

  function tap(point: string) {
    if (current.includes(point)) return
    if (second) setRepeated(repeated + point)
    else setPattern(pattern + point)
  }
  function reset() {
    setPattern('')
    setRepeated('')
    setSecond(false)
  }
  return (
    <Card title="九宫格图案" subtitle="先在银行 App 修改，再到这里同步">
      <div className="flex flex-col items-center gap-[18px] py-2">
        <span className="text-muted text-xs">{second ? '再次点选相同图案' : '点选 4–9 个不重复的点'}</span>
        <div className="grid grid-cols-3 gap-x-6 gap-y-[18px]">
          {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => {
            const point = String(n)
            const on = current.includes(point)
            return (
              <button
                key={n}
                type="button"
                aria-label={`第 ${n} 个点`}
                aria-pressed={on}
                onClick={() => tap(point)}
                className="flex size-9 items-center justify-center"
              >
                <motion.span
                  animate={{ scale: on ? 1.12 : 1, backgroundColor: on ? '#e04252' : '#616161' }}
                  transition={{ type: 'spring', stiffness: 500, damping: 22 }}
                  className="block size-[27px] rounded-full"
                />
              </button>
            )
          })}
        </div>
        <span className="text-[11px] text-muted">已选 {current.length} 个点</span>
        <div className="flex gap-2">
          <Button onClick={reset}>重画</Button>
          {second ? (
            <Button
              variant="primary"
              disabled={pattern !== repeated || pattern.length < 4}
              onClick={() => {
                const value = pattern
                reset()
                action('保存凭据', () => api('POST', '/api/credentials/login-pattern', { new: value }))
              }}
            >
              保存图案
            </Button>
          ) : (
            <Button disabled={pattern.length < 4} onClick={() => setSecond(true)}>
              再画一次
            </Button>
          )}
        </div>
      </div>
    </Card>
  )
}

const sixDigits = (value: string) => /^\d{6}$/.test(value)

function PasswordCard() {
  const action = useAction()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const mismatch = again.length > 0 && next !== again
  const input = (label: string, value: string, set: (v: string) => void) => (
    <Field label={label}>
      <Input
        type="password"
        autoComplete="off"
        inputMode="numeric"
        maxLength={6}
        placeholder="6 位数字"
        value={value}
        onChange={(e) => set(e.target.value)}
      />
    </Field>
  )
  return (
    <Card title="交易密码" subtitle="先在银行 App 修改，再输入当前密码同步">
      {input('当前密码', current, setCurrent)}
      {input('新密码', next, setNext)}
      {input('再次输入新密码', again, setAgain)}
      {mismatch ? <Hint tone="accent">两次输入的新密码不一致</Hint> : <Hint>保存后立即清空输入。</Hint>}
      <Button
        variant="primary"
        className="self-end"
        disabled={next !== again || !sixDigits(next) || !sixDigits(current)}
        onClick={() => {
          const body = { current, new: next }
          setCurrent('')
          setNext('')
          setAgain('')
          action('保存凭据', () => api('POST', '/api/credentials/payment-password', body))
        }}
      >
        保存交易密码
      </Button>
    </Card>
  )
}

// ---------------------------------------------------------------- 推送通知

const PUSH_SERVER = /^https:\/\/\S+$/i
const PUSH_TOPIC = /^[-_A-Za-z0-9]{1,64}$/

function PushCard() {
  const busy = useUI((s) => s.busy)
  const action = useAction()
  const qc = useQueryClient()
  const { data } = useQuery({ ...q.push, staleTime: 0 })
  const [server, setServer] = useState('')
  const [topic, setTopic] = useState('')
  const [token, setToken] = useState('')
  const [result, setResult] = useState<{ tone: Tone; text: string } | null>(null)
  const [clearOpen, setClearOpen] = useState(false)
  const configured = data?.configured === true
  const disabled = !data || busy

  useEffect(() => {
    if (!data) return
    setServer(data.server ?? '')
    setTopic(data.topic ?? '')
  }, [data])

  const valid =
    PUSH_SERVER.test(server.trim()) &&
    PUSH_TOPIC.test(topic.trim()) &&
    (token.trim().length > 0 || configured)

  async function save() {
    setResult(null)
    const saved = await action('保存推送配置', () =>
      api<PushConfig>('PUT', '/api/push', {
        server: server.trim(),
        topic: topic.trim(),
        token: token.trim(),
      }),
    )
    if (!saved) return
    qc.setQueryData(q.push.queryKey, saved)
    setToken('')
    setServer(saved.server ?? server.trim())
    setTopic(saved.topic ?? topic.trim())
    setResult({ tone: 'good', text: '已保存；之后的通知会发到这个频道。' })
  }

  async function test() {
    setResult(null)
    const sent = await action('发送测试推送', () => api<PushTestResult>('POST', '/api/push/test'), false)
    if (!sent) return
    setResult(
      sent.sent
        ? { tone: 'good', text: '测试推送已发送，请在手机上查看。' }
        : { tone: 'accent', text: `测试推送失败：${sent.error ?? '原因未知'}。` },
    )
  }

  async function clear() {
    setResult(null)
    const cleared = await action('清除推送配置', () => api<PushConfig>('DELETE', '/api/push'))
    if (!cleared) return
    qc.setQueryData(q.push.queryKey, cleared)
    setServer('')
    setTopic('')
    setToken('')
    setResult({ tone: 'warn', text: '已清除推送配置；通知只写日志。' })
  }

  return (
    <Card
      testId="push-card"
      title="推送通知"
      subtitle="成交、失败和值守状态发到手机；服务器、频道和令牌只保存在本机钥匙串。"
      badge={<Badge tone={configured ? 'good' : 'warn'}>{configured ? '已配置' : '未配置'}</Badge>}
    >
      <div className="grid grid-cols-2 gap-4 rounded-xl bg-field/60 p-3.5">
        <div className="flex min-w-0 flex-col gap-[3px]">
          <span className="text-[10px] text-muted">服务器地址</span>
          <span className="truncate font-medium text-xs">{data?.server ?? '—'}</span>
        </div>
        <div className="flex min-w-0 flex-col gap-[3px]">
          <span className="text-[10px] text-muted">频道</span>
          <span className="truncate font-medium text-xs">{data?.topic ?? '—'}</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Field label="服务器地址">
          <Input
            data-testid="push-server"
            value={server}
            disabled={disabled}
            autoComplete="off"
            placeholder="https://ntfy.example.com/"
            onChange={(e) => {
              setServer(e.target.value)
              setResult(null)
            }}
          />
        </Field>
        <Field label="频道">
          <Input
            data-testid="push-topic"
            value={topic}
            disabled={disabled}
            autoComplete="off"
            placeholder="如 cmb"
            onChange={(e) => {
              setTopic(e.target.value)
              setResult(null)
            }}
          />
        </Field>
      </div>

      <Field label="访问令牌">
        <Input
          data-testid="push-token"
          type="password"
          value={token}
          disabled={disabled}
          autoComplete="off"
          placeholder={configured ? '已保存，留空不修改' : '首次配置必须填写'}
          onChange={(e) => {
            setToken(e.target.value)
            setResult(null)
          }}
        />
      </Field>

      <Hint>令牌在推送服务的管理页面新建，只授权这个频道。这里保存后不会回显。</Hint>
      {result && <Hint tone={result.tone}>{result.text}</Hint>}

      <div className="flex items-center gap-2">
        <Button
          data-testid="push-clear"
          variant="ghost"
          disabled={disabled || !configured}
          onClick={() => setClearOpen(true)}
        >
          清除配置
        </Button>
        <span className="flex-1" />
        <Button data-testid="push-test" disabled={disabled || !configured} onClick={test}>
          发送测试推送
        </Button>
        <Button data-testid="push-save" variant="primary" disabled={disabled || !valid} onClick={save}>
          保存
        </Button>
      </div>

      <Confirm
        open={clearOpen}
        onOpenChange={setClearOpen}
        title="清除推送配置？"
        message="会删除本机钥匙串里的服务器、频道和令牌，之后的通知只写入日志。"
        cancel="取消"
        confirm="确认清除"
        onConfirm={() => {
          setClearOpen(false)
          clear()
        }}
      />
    </Card>
  )
}
