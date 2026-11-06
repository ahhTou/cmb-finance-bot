import { useQuery, useQueryClient } from '@tanstack/react-query'
import { History as HistoryIcon, PanelLeft } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import { api } from '../api/client'
import { q, useAction } from '../api/hooks'
import type { HistoryRecord } from '../api/types'
import { LogDialog, LogPreview } from '../components/shared'
import { Button } from '../components/ui/button'
import { Badge, Detail } from '../components/ui/card'
import { cn, copyText, phaseName, phaseTone, shortTime, type Tone, toneBg, toneText } from '../lib/utils'
import { useUI } from '../store'

export function HistoryPage() {
  const busy = useUI((s) => s.busy)
  const action = useAction()
  const qc = useQueryClient()
  const { data } = useQuery(q.history)
  const { data: log } = useQuery(q.log(800))
  const [selected, setSelected] = useState(0)
  const [showLog, setShowLog] = useState(false)
  const records = data?.records ?? []
  const record = records[selected] ?? records[0]
  const count = (phase: string) => records.filter((r) => r.phase === phase).length
  const lines = log?.lines ?? []

  return (
    <div className="flex h-full flex-col gap-3.5 px-[26px]">
      <div className="grid grid-cols-5 gap-2.5">
        <Stat title="总记录" value={data?.total ?? 0} />
        <Stat title="已完成" value={count('done')} tone="good" />
        <Stat title="已中止" value={count('aborted')} tone="warn" />
        <Stat title="已取消" value={count('disarmed')} tone="muted" />
        <Stat title="演练" value={records.filter((r) => r.dry_run).length} tone="muted" />
      </div>
      <div className="flex min-h-0 flex-1 gap-3.5">
        <section className="flex w-[330px] shrink-0 flex-col gap-2.5 rounded-[14px] bg-card p-4">
          <div className="flex items-center gap-2">
            <h2 className="flex-1 font-semibold text-[13px]">历史任务</h2>
            <span className="text-[10px] text-muted">
              {records.length} / {data?.total ?? 0}
            </span>
            <Button
              disabled={busy}
              onClick={() =>
                action(
                  '加载历史',
                  () =>
                    Promise.all([
                      qc.fetchQuery({ ...q.history, staleTime: 0 }),
                      qc.fetchQuery({ ...q.log(800), staleTime: 0 }),
                    ]),
                  false,
                )
              }
            >
              刷新
            </Button>
          </div>
          {records.length === 0 ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center">
              <HistoryIcon className="size-5 text-muted" />
              <span className="font-medium text-xs">暂无历史任务</span>
              <span className="text-[10px] text-muted">
                完成一次值守后会自动写入 var/night/history.jsonl。
              </span>
            </div>
          ) : (
            <ul className="flex min-h-0 flex-col gap-[5px] overflow-y-auto">
              {records.map((r, index) => (
                <li key={`${r.armed_at}-${r.code}`}>
                  <Row record={r} selected={r === record} onSelect={() => setSelected(index)} />
                </li>
              ))}
            </ul>
          )}
        </section>
        <section
          data-testid="history-detail"
          className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-[14px] bg-card p-[18px]"
        >
          {record ? (
            <AnimatePresence mode="wait">
              <motion.div
                key={`${record.armed_at}-${selected}`}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.16 }}
                className="flex min-h-0 flex-1 flex-col gap-4"
              >
                <div className="flex shrink-0 flex-col gap-4">
                  <RecordDetail record={record} />
                </div>
                <div className="h-px shrink-0 bg-white/5" />
                <div className="flex shrink-0 items-center gap-2">
                  <h3 className="flex-1 font-semibold text-xs">值守日志</h3>
                  <Button
                    disabled={busy}
                    onClick={() =>
                      action('加载日志', () => qc.fetchQuery({ ...q.log(800), staleTime: 0 }), false)
                    }
                  >
                    刷新日志
                  </Button>
                  <Button onClick={() => setShowLog(true)}>查看全部</Button>
                </div>
                {/* No scrollbar in this area: the newest lines fill the space and
                    the rest is read in the 查看全部 dialog. */}
                <LogPreview
                  lines={lines}
                  maxLines={40}
                  align="bottom"
                  fitLines
                  testId="history-log"
                  className="min-h-0 flex-1 rounded-lg bg-field px-2.5 py-2"
                />
                <div className="flex shrink-0 items-center gap-2">
                  <Button disabled={!lines.length} onClick={() => copyText(lines.join('\n'))}>
                    复制日志
                  </Button>
                  <Button onClick={() => action('打开日志', () => api('POST', '/api/open-log'), false)}>
                    打开文件
                  </Button>
                  <span className="flex-1" />
                  <span className="text-[10px] text-muted">全局 watch.log，不按任务拆分</span>
                </div>
              </motion.div>
            </AnimatePresence>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-2.5">
              <PanelLeft className="size-5 text-muted" />
              <span className="text-muted text-xs">选择左侧记录查看详情</span>
              <Button onClick={() => setShowLog(true)}>查看值守日志</Button>
            </div>
          )}
        </section>
      </div>
      <LogDialog open={showLog} onOpenChange={setShowLog} />
    </div>
  )
}

function RecordDetail({ record }: { record: HistoryRecord }) {
  const phase = record.phase ?? ''
  const redemption = record.mode === 'redemption'
  return (
    <>
      <div className="flex items-baseline gap-2.5">
        <span className="font-rounded font-semibold text-xl">{record.code ?? '—'}</span>
        <span className="font-medium text-muted text-sm">{record.amount ?? '—'} 元</span>
        <span className="flex-1" />
        <Badge tone={phaseTone(phase)}>{phaseName(phase)}</Badge>
        {record.dry_run && <Badge>演练</Badge>}
      </div>
      <div className="grid grid-cols-3 gap-x-3.5 gap-y-3">
        <Detail title={redemption ? '额度放出' : '开售时间'} value={shortTime(record.at)} />
        <Detail
          title="模式"
          value={redemption ? `不定时抢购 · ${record.window_minutes ?? 3} 分钟` : '首发'}
        />
        <Detail title="布防时间" value={shortTime(record.armed_at)} />
        <Detail title="结束时间" value={shortTime(record.ended_at)} />
        <Detail title="提交时间" value={shortTime(record.fired_at)} />
        <Detail title="阶段" value={phaseName(phase)} />
        <Detail title="结果" value={record.result ?? '未记录'} />
      </div>
      {!!record.resumes?.length && (
        <div className="flex flex-col gap-1.5">
          <span className="text-[11px] text-muted">恢复记录</span>
          {record.resumes.map((resume, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: resume entries have no id
            <span key={index} className="selectable text-[11px]">
              {shortTime(resume.at)} · {resume.by ?? '—'} · {resume.reason ?? '—'}
            </span>
          ))}
        </div>
      )}
    </>
  )
}

function Row({
  record,
  selected,
  onSelect,
}: {
  record: HistoryRecord
  selected: boolean
  onSelect: () => void
}) {
  const phase = record.phase ?? ''
  return (
    <button
      type="button"
      onClick={onSelect}
      className="relative flex w-full items-center gap-[9px] rounded-lg p-[9px] text-left"
    >
      {selected && (
        <motion.span
          layoutId="history-selection"
          className="absolute inset-0 rounded-lg bg-button/55"
          transition={{ type: 'spring', stiffness: 500, damping: 40 }}
        />
      )}
      <span className={cn('relative size-[7px] shrink-0 rounded-full', toneBg[phaseTone(phase)])} />
      <span className="relative flex min-w-0 flex-1 flex-col gap-[3px]">
        <span className="flex items-center gap-[5px] font-medium text-xs">
          {record.code ?? '—'}
          {record.dry_run && <Badge>演练</Badge>}
        </span>
        <span className="truncate text-[10px] text-muted">
          {record.amount ?? '—'} 元 · {shortTime(record.at)}
        </span>
      </span>
      <span className="relative flex flex-col items-end gap-[3px]">
        <span className={cn('font-medium text-[10px]', toneText[phaseTone(phase)])}>{phaseName(phase)}</span>
        <span className="text-[9px] text-muted">{shortTime(record.ended_at)}</span>
      </span>
    </button>
  )
}

function Stat({ title, value, tone }: { title: string; value: number; tone?: Tone }) {
  return (
    <div className="flex flex-col gap-[3px] rounded-[10px] bg-card px-3 py-[9px]">
      <span className="text-[10px] text-muted">{title}</span>
      <span
        className={cn(
          'font-rounded font-semibold text-[17px] tabular-nums',
          tone ? toneText[tone] : 'text-[#ebebeb]',
        )}
      >
        {value}
      </span>
    </div>
  )
}
