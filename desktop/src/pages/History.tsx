import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, History as HistoryIcon, PanelLeft } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import { q, useAction, useWatch } from '../api/hooks'
import type { HistoryRecord } from '../api/types'
import { LogDialog, LogPreview } from '../components/shared'
import { Button } from '../components/ui/button'
import { Badge, Detail } from '../components/ui/card'
import {
  amountText,
  clockText,
  durationLine,
  durationValue,
  FILTER_CARDS,
  filterRecords,
  filterTitle,
  type HistoryFilter,
  matchFilter,
  modeText,
  outcomeName,
  outcomeOf,
  outcomeTone,
  RECENT_LIMIT,
  realRecords,
  recentTasks,
  recordKey,
  resultText,
  resumeCount,
} from '../lib/history'
import { cn, copyText, phaseName, phaseTone, shortTime, type Tone, toneBg, toneText } from '../lib/utils'
import { useUI } from '../store'

/**
 * History is two screens tall by default: the first screen is a rich overview of
 * the latest real successes and failures (drills and the saved test item's code
 * are filtered out), the second is the complete record list the page used to be.
 * The first screen's bottom hint and metric cards scroll/jump to the second.
 */
export function HistoryPage() {
  const busy = useUI((s) => s.busy)
  const action = useAction()
  const qc = useQueryClient()
  const { data } = useQuery(q.history)
  const { data: log } = useQuery(q.log(800))
  const { testItem } = useWatch()
  const records = useMemo(() => data?.records ?? [], [data])
  const testCode = testItem?.code ?? null
  const real = useMemo(() => realRecords(records, testCode), [records, testCode])
  const recent = useMemo(() => recentTasks(records, testCode), [records, testCode])
  const successCount = useMemo(() => real.filter((row) => outcomeOf(row) === 'success').length, [real])
  const failedCount = useMemo(() => real.filter((row) => outcomeOf(row) === 'failed').length, [real])
  const [filter, setFilter] = useState<HistoryFilter>('all')
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [showLog, setShowLog] = useState(false)
  const scroller = useRef<HTMLDivElement>(null)
  const visible = useMemo(() => filterRecords(records, filter), [records, filter])
  const record = visible.find((row) => recordKey(row) === selectedKey) ?? visible[0]
  const lines = log?.lines ?? []

  /** One screen = the scroll container's own height, so the second screen starts there. */
  const scrollToFull = () => {
    const el = scroller.current
    el?.scrollTo({ top: el.clientHeight, behavior: 'smooth' })
  }
  const scrollToTop = () => scroller.current?.scrollTo({ top: 0, behavior: 'smooth' })
  const openRecord = (target: HistoryRecord) => {
    if (!matchFilter(target, filter)) setFilter('all')
    setSelectedKey(recordKey(target))
    scrollToFull()
  }
  const refresh = () =>
    action(
      '加载历史',
      () =>
        Promise.all([
          qc.fetchQuery({ ...q.history, staleTime: 0 }),
          qc.fetchQuery({ ...q.log(800), staleTime: 0 }),
        ]),
      false,
    )

  return (
    <>
      <div
        ref={scroller}
        data-testid="history-scroll"
        className="no-scrollbar h-full snap-y snap-mandatory overflow-x-hidden overflow-y-auto"
      >
        <section data-testid="history-overview" className="flex h-full snap-start flex-col gap-2.5 px-[26px]">
          <div className="flex shrink-0 items-end gap-3">
            <div className="flex min-w-0 flex-col gap-[3px]">
              <h2 className="font-semibold text-[13px]">近期布防</h2>
              <p className="truncate text-[10px] text-muted">
                最近 {recent.length} 条真实布防 · 成功 {successCount} · 失败 {failedCount}
                {records.length > real.length
                  ? ` · 已过滤 ${records.length - real.length} 条演练/测试记录`
                  : ''}
              </p>
            </div>
            <span className="flex-1" />
            <span className="shrink-0 text-[10px] text-muted">首屏 · 成功与失败共 {RECENT_LIMIT} 条</span>
          </div>
          {recent.length ? (
            <ul data-testid="recent-list" className="grid min-h-0 flex-1 grid-cols-2 grid-rows-4 gap-2.5">
              {recent.map((row) => (
                <li key={recordKey(row)} className="flex min-h-0">
                  <RecentCard
                    record={row}
                    tone={outcomeTone(outcomeOf(row))}
                    onOpen={() => openRecord(row)}
                  />
                </li>
              ))}
            </ul>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center">
              <HistoryIcon className="size-5 text-muted" />
              <span className="font-medium text-xs">还没有近期布防</span>
              <span className="text-[10px] text-muted">
                完成一次真实值守后会自动写入 var/night/history.jsonl。
              </span>
            </div>
          )}
          <button
            type="button"
            data-testid="history-scroll-hint"
            onClick={scrollToFull}
            className="flex shrink-0 items-center justify-center gap-1.5 rounded-lg py-1.5 text-[11px] text-muted transition-colors hover:bg-card hover:text-fg"
          >
            <motion.span
              animate={{ y: [0, 3, 0] }}
              transition={{ repeat: Number.POSITIVE_INFINITY, duration: 1.8, ease: 'easeInOut' }}
            >
              <ChevronDown className="size-3.5" />
            </motion.span>
            下滑查看完整历史
            <span className="text-[10px] text-muted">共 {records.length} 条 · 点指标卡片可筛选类型</span>
          </button>
        </section>

        <section data-testid="history-full" className="flex h-full snap-start flex-col gap-2.5 px-[26px]">
          <div className="flex shrink-0 items-center gap-2">
            <h2 className="font-semibold text-[13px]">完整历史</h2>
            <span className="text-[10px] text-muted">点击指标卡片按类型筛选，再次点击取消</span>
            <span className="flex-1" />
            <span className="text-[10px] text-muted">
              {visible.length} / {records.length} 条
            </span>
            <Button size="compact" onClick={scrollToTop}>
              回到首屏
            </Button>
          </div>
          <div className="grid shrink-0 grid-cols-5 gap-2.5">
            {FILTER_CARDS.map(({ kind, title, tone }) => {
              const active = filter === kind
              const count = filterRecords(records, kind).length
              return (
                <button
                  key={kind}
                  type="button"
                  data-testid={`filter-${kind}`}
                  aria-pressed={active}
                  title={`只看${title}`}
                  onClick={() => setFilter(active ? 'all' : kind)}
                  className={cn(
                    'relative flex flex-col gap-[3px] rounded-[10px] bg-card px-3 py-[9px] text-left transition-colors hover:bg-card-hover',
                    active && 'ring-1 ring-accent/60',
                  )}
                >
                  <span className="text-[10px] text-muted">{title}</span>
                  <span
                    className={cn(
                      'font-rounded font-semibold text-[17px] tabular-nums',
                      tone ? toneText[tone] : 'text-[#ebebeb]',
                    )}
                  >
                    {count}
                  </span>
                  {active && kind !== 'all' && (
                    <span className="absolute top-2 right-2 size-1.5 rounded-full bg-accent" />
                  )}
                </button>
              )
            })}
          </div>
          <div className="flex min-h-0 flex-1 gap-3.5">
            <section className="flex w-[330px] shrink-0 flex-col gap-2.5 rounded-[14px] bg-card p-4">
              <div className="flex items-center gap-2">
                <h2 className="flex-1 font-semibold text-[13px]">历史任务</h2>
                <span className="text-[10px] text-muted">
                  {visible.length} / {records.length}
                </span>
                <Button disabled={busy} onClick={refresh}>
                  刷新
                </Button>
              </div>
              {visible.length === 0 ? (
                <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center">
                  <HistoryIcon className="size-5 text-muted" />
                  <span className="font-medium text-xs">没有「{filterTitle(filter)}」记录</span>
                  <span className="text-[10px] text-muted">换成其它类型，或查看全部记录。</span>
                  <Button onClick={() => setFilter('all')}>查看全部</Button>
                </div>
              ) : (
                <ul data-testid="history-list" className="flex min-h-0 flex-col gap-[5px] overflow-y-auto">
                  {visible.map((row) => (
                    <li key={recordKey(row)}>
                      <Row
                        record={row}
                        selected={recordKey(row) === (record ? recordKey(record) : '')}
                        onSelect={() => setSelectedKey(recordKey(row))}
                      />
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
                    key={recordKey(record)}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.16 }}
                    className="flex min-h-0 flex-1 flex-col gap-3"
                  >
                    <div className="flex shrink-0 flex-col gap-2.5">
                      <RecordDetail record={record} />
                    </div>
                    <div className="h-px shrink-0 bg-white/5" />
                    <div className="flex shrink-0 items-center gap-2">
                      <h3 className="flex-1 font-semibold text-xs">值守日志</h3>
                      <Button
                        size="compact"
                        disabled={busy}
                        onClick={() =>
                          action('加载日志', () => qc.fetchQuery({ ...q.log(800), staleTime: 0 }), false)
                        }
                      >
                        刷新日志
                      </Button>
                      <Button size="compact" onClick={() => setShowLog(true)}>
                        查看全部
                      </Button>
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
                      <Button
                        size="compact"
                        disabled={!lines.length}
                        onClick={() => copyText(lines.join('\n'))}
                      >
                        复制日志
                      </Button>
                      <Button
                        size="compact"
                        onClick={() => action('打开日志', () => api('POST', '/api/open-log'), false)}
                      >
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
        </section>
      </div>
      <LogDialog open={showLog} onOpenChange={setShowLog} />
    </>
  )
}

/** Rich recent-task card: product, amount, mode, times, result and durations. */
function RecentCard({ record, tone, onOpen }: { record: HistoryRecord; tone: Tone; onOpen: () => void }) {
  const outcome = outcomeOf(record)
  const resumes = resumeCount(record)
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex h-full min-h-0 w-full min-w-0 flex-col justify-center gap-1 overflow-hidden rounded-[10px] bg-field px-2.5 py-2 text-left transition-colors hover:bg-card-hover"
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className="truncate font-rounded font-semibold text-[14px]">{record.code ?? '—'}</span>
        <span className="shrink-0 text-[10px] text-muted">{amountText(record)} 元</span>
        <span className="flex-1" />
        <Badge tone={outcomeTone(outcome)}>{outcomeName(outcome)}</Badge>
      </div>
      <div className="flex min-w-0 items-center gap-1.5 text-[10px] text-muted">
        <span className="truncate">{modeText(record)}</span>
        <span className="text-white/15">·</span>
        <span className="shrink-0">
          {record.mode === 'redemption' ? '放出' : '开售'} {shortTime(record.at)}
        </span>
        {resumes > 0 && <span className="shrink-0 text-warn">恢复 {resumes} 次</span>}
      </div>
      <p className={cn('line-clamp-2 text-[11px] leading-snug', toneText[tone])}>{resultText(record)}</p>
      <div className="grid shrink-0 grid-cols-4 gap-x-2 border-white/5 border-t pt-1">
        <CardFact title="布防" value={clockText(record.armed_at)} />
        <CardFact title="提交" value={clockText(record.fired_at)} />
        <CardFact title="结束" value={clockText(record.ended_at)} />
        <CardFact title="耗时" value={durationValue(record)} hint={durationLine(record)} />
      </div>
    </button>
  )
}

function CardFact({ title, value, hint }: { title: string; value: string; hint?: string }) {
  return (
    <div className="flex min-w-0 flex-col">
      <span className="text-[9px] text-muted">{title}</span>
      <span title={hint} className="truncate font-medium text-[10px]">
        {value}
      </span>
    </div>
  )
}

function RecordDetail({ record }: { record: HistoryRecord }) {
  const phase = record.phase ?? ''
  const redemption = record.mode === 'redemption'
  const outcome = outcomeOf(record)
  const resumes = record.resumes ?? []
  return (
    <>
      <div className="flex items-baseline gap-2.5">
        <span className="font-rounded font-semibold text-xl">{record.code ?? '—'}</span>
        <span className="font-medium text-muted text-sm">{record.amount ?? '—'} 元</span>
        <span className="flex-1" />
        <Badge tone={outcomeTone(outcome)}>{outcomeName(outcome)}</Badge>
        <Badge tone={phaseTone(phase)}>{phaseName(phase)}</Badge>
      </div>
      <p className={cn('line-clamp-2 font-medium text-[13px]', toneText[outcomeTone(outcome)])}>
        {resultText(record)}
      </p>
      <div className="grid grid-cols-2 gap-x-3.5 gap-y-2.5">
        <Detail title={redemption ? '额度放出' : '开售时间'} value={shortTime(record.at)} />
        <Detail title="模式" value={modeText(record)} />
        <Detail title="布防时间" value={shortTime(record.armed_at)} />
        <Detail title="提交时间" value={shortTime(record.fired_at)} />
        <Detail title="结束时间" value={shortTime(record.ended_at)} />
        <Detail title="耗时" value={durationLine(record)} />
      </div>
      {resumes.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <span className="text-[11px] text-muted">恢复记录（{resumes.length} 次）</span>
          {resumes.map((resume, index) => (
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
  const outcome = outcomeOf(record)
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
      <span className={cn('relative size-[7px] shrink-0 rounded-full', toneBg[outcomeTone(outcome)])} />
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
        <span className={cn('font-medium text-[10px]', toneText[outcomeTone(outcome)])}>
          {outcomeName(outcome)}
        </span>
        <span className="text-[9px] text-muted">{shortTime(record.ended_at)}</span>
      </span>
    </button>
  )
}
