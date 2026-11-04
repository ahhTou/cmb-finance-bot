import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { api, isTauri, resetBackend } from '../api/client'
import { q, useAction, useWatch } from '../api/hooks'
import type { PurchaseSettings } from '../api/types'
import { Button } from '../components/ui/button'
import { Card, Detail, Hint } from '../components/ui/card'
import { Field, Input } from '../components/ui/form'
import { cn } from '../lib/utils'
import { type BackendConfig, backendConfig, setBackendConfig } from '../platform'
import { useUI } from '../store'

export function SettingsPage() {
  const w = useWatch()
  const busy = useUI((s) => s.busy)
  const locked = w.credentialsDisabled || busy
  return (
    <div className="flex flex-col gap-4 overflow-y-auto px-[26px] pb-2">
      <ProjectCard />
      <RetryCard />
      <Card title="凭据状态" subtitle="这里只同步脚本保存的值，不会修改银行 App 中的设置。">
        <div className="flex">
          <Detail title="登录与交易凭据" value={w.credentialState} />
          <Detail title="邮件通知" value={w.mailConfigured ? '已配置' : '未配置'} />
        </div>
      </Card>
      <div className={cn('grid grid-cols-2 gap-4', locked && 'pointer-events-none opacity-60')}>
        <PatternCard />
        <PasswordCard />
      </div>
    </div>
  )
}

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

const GROUPS: [string, [string, string, number, number, number][]][] = [
  [
    '首发模式',
    [
      ['first_offset_ms', '首次查询延后（毫秒）', 200, 0, 10000],
      ['first_max_retries', '首次之外最多重试（次）', 5, 0, 100],
    ],
  ],
  [
    '不定时抢购模式',
    [
      ['irregular_advance_ms', '首次查询提前（毫秒）', 200, 0, 10000],
      ['irregular_window_minutes', '最长查询窗口（分钟）', 5, 1, 60],
      ['irregular_burst_seconds', '高频阶段时长（秒）', 15, 0, 3600],
      ['irregular_retry_min_ms', '高频间隔下限（毫秒）', 250, 1, 60000],
      ['irregular_retry_max_ms', '高频间隔上限（毫秒）', 400, 1, 60000],
      ['irregular_ramp_seconds', '过渡结束（秒）', 20, 0, 3600],
      ['irregular_slow_min_ms', '降频间隔下限（毫秒）', 1000, 1, 60000],
      ['irregular_slow_max_ms', '降频间隔上限（毫秒）', 2000, 1, 60000],
      ['irregular_idle_after_seconds', '进入低频（秒）', 60, 0, 3600],
      ['irregular_idle_min_ms', '低频间隔下限（毫秒）', 2500, 1, 60000],
      ['irregular_idle_max_ms', '低频间隔上限（毫秒）', 4000, 1, 60000],
    ],
  ],
  [
    '单笔购买',
    [
      ['reopen_deadline', '直接购买总时限（秒）', 60, 1, 300],
      ['drill_form_deadline', '单笔购买演练总时限（秒）', 10, 1, 300],
    ],
  ],
]
const NOTES: Record<string, string> = {
  首发模式: '重试次数不含首次查询；无额度时立即串行重试。',
  不定时抢购模式:
    '首次查询在设定时间之前发出。无额度后按已查询时长分段随机等待：高频阶段内用高频间隔，到过渡结束逐渐放慢到降频间隔，进入低频后用低频间隔，直到窗口结束。时长和窗口都从首次计划查询时间计算。',
}
const FIELDS = GROUPS.flatMap(([, rows]) => rows)

function RetryCard() {
  const busy = useUI((s) => s.busy)
  const action = useAction()
  const qc = useQueryClient()
  const { data } = useQuery({ ...q.settings, staleTime: 0 })
  const [saved, setSaved] = useState(false)
  const form = useForm<Record<string, string>>({ mode: 'onChange' })
  const values = form.watch()

  useEffect(() => {
    if (data) {
      form.reset(
        Object.fromEntries(FIELDS.map(([key, , initial]) => [key, String(data.settings[key] ?? initial)])),
      )
    }
  }, [data, form])

  const valid =
    FIELDS.every(([key, , , min, max]) => {
      const value = values[key]
      return /^\d+$/.test(value ?? '') && Number(value) >= min && Number(value) <= max
    }) &&
    (['retry', 'slow', 'idle'] as const).every(
      (tier) => Number(values[`irregular_${tier}_min_ms`]) <= Number(values[`irregular_${tier}_max_ms`]),
    ) &&
    Number(values.irregular_burst_seconds) <= Number(values.irregular_ramp_seconds) &&
    Number(values.irregular_ramp_seconds) <= Number(values.irregular_idle_after_seconds)

  const save = form.handleSubmit(async (raw) => {
    const body = Object.fromEntries(FIELDS.map(([key]) => [key, Number(raw[key])]))
    const result = await action('保存值守配置', () => api<PurchaseSettings>('PUT', '/api/settings', body))
    if (result) {
      qc.setQueryData(q.settings.queryKey, result)
      setSaved(true)
    }
  })

  return (
    <Card title="值守配置" subtitle="新布防使用当前配置；已布防任务保持原值">
      <form className="flex flex-col gap-4" onSubmit={save} onChange={() => setSaved(false)}>
        {GROUPS.map(([title, rows]) => (
          <div key={title} className="flex flex-col gap-2">
            <h3 className="font-semibold text-[13px]">{title}</h3>
            {rows.map(([key, label, initial]) => (
              <label key={key} className="flex items-center justify-between gap-3">
                <span className="text-[11px] text-muted">{label}</span>
                <Input
                  className="w-[110px]"
                  inputMode="numeric"
                  placeholder={String(initial)}
                  disabled={!data || busy}
                  {...form.register(key)}
                />
              </label>
            ))}
            {NOTES[title] && <Hint>{NOTES[title]}</Hint>}
          </div>
        ))}
        <div className="flex items-center">
          {saved && <span className="text-[11px] text-muted">配置已保存</span>}
          <span className="flex-1" />
          <Button type="submit" variant="primary" disabled={!data || !valid || busy}>
            保存值守配置
          </Button>
        </div>
      </form>
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
  return (
    <Card title="交易密码" subtitle="请输入当前密码以验证修改">
      <Input
        type="password"
        autoComplete="off"
        placeholder="当前密码"
        value={current}
        onChange={(e) => setCurrent(e.target.value)}
      />
      <Input
        type="password"
        autoComplete="off"
        placeholder="新密码"
        value={next}
        onChange={(e) => setNext(e.target.value)}
      />
      <Input
        type="password"
        autoComplete="off"
        placeholder="再次输入新密码"
        value={again}
        onChange={(e) => setAgain(e.target.value)}
      />
      <Hint>6 位数字，保存后立即清空输入。</Hint>
      <Button
        variant="primary"
        className="self-start"
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
