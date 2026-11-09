import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Clock, Hammer, type LucideIcon, Repeat, ShieldCheck, Zap } from 'lucide-react'
import { type ReactNode, useState } from 'react'
import { api } from '../api/client'
import { q, useAction, useWatch } from '../api/hooks'
import type { Mode } from '../api/types'
import { ArmDialog } from '../components/ArmDialog'
import { Button } from '../components/ui/button'
import { Badge, IconTile, Metric } from '../components/ui/card'
import { Confirm } from '../components/ui/dialog'
import { ageText, phaseName, phaseTone, shortTime, type Tone } from '../lib/utils'
import { useUI } from '../store'

export function TasksPage() {
  const w = useWatch()
  const busy = useUI((s) => s.busy)
  const action = useAction()
  const navigate = useNavigate()
  const [armMode, setArmMode] = useState<Mode | null>(null)
  const [confirmDisarm, setConfirmDisarm] = useState(false)
  const taskMode = w.task?.mode ?? 'first_launch'
  // Plan mode owns arming while it runs or is paused: manual tasks would collide.
  const { data: planView } = useQuery(q.plan)
  const planPhase = planView?.plan?.phase
  const planMode = planPhase === 'running' || planPhase === 'paused'

  function modeCard(mode: Mode) {
    const redemption = mode === 'redemption'
    const mine = w.active && (redemption ? taskMode === 'redemption' : taskMode !== 'redemption')
    const badge: [string, Tone] = mine
      ? [phaseName(w.phase), phaseTone(w.phase)]
      : planMode
        ? ['计划模式中', 'warn']
        : w.active
          ? ['其他值守中', 'warn']
          : ['可用', 'good']
    const ended = w.task && !w.active && (redemption ? taskMode === 'redemption' : taskMode !== 'redemption')
    return (
      <ModeCard
        testId={`mode-${mode}`}
        icon={redemption ? Clock : Zap}
        tone={redemption ? 'purple' : 'accent'}
        title={redemption ? '不定时抢购模式' : '首发模式'}
        subtitle={redemption ? '常用时间盯盘，有额度就买' : '开售准点抢一只新发理财'}
        badge={badge}
        actions={
          mine ? (
            <>
              <Button disabled={busy} onClick={() => action('刷新状态', () => Promise.resolve())}>
                刷新
              </Button>
              <Button disabled={busy || w.phase === 'firing'} onClick={() => setConfirmDisarm(true)}>
                取消布防
              </Button>
            </>
          ) : (
            <>
              <Button variant="primary" disabled={w.active || planMode} onClick={() => setArmMode(mode)}>
                新建布防
              </Button>
              <Button onClick={() => navigate({ to: '/history' })}>查看历史</Button>
            </>
          )
        }
      >
        {planMode && (
          <p data-testid="plan-mode-hint" className="text-[11px] leading-snug text-warn">
            当前有计划模式，请回到计划模式中添加任务。
          </p>
        )}
        {mine ? (
          <ActiveSummary redemption={redemption} />
        ) : (
          <>
            <Blurb>
              {redemption
                ? '登录后进入购买页等待，按配置时间开始查询；无额度时在同页重试，有额度才进入购买。'
                : '按配置冷启动并登录，提前进入购买页等待；到点查询，有额度才提交一次。'}
            </Blurb>
            {redemption ? (
              <>
                <Feature icon={Clock}>00:15 / 09:00 / 09:15 / 10:15 / 11:15，支持自定义</Feature>
                <Feature icon={Repeat}>同一购买页等待与查询</Feature>
                <Feature icon={ShieldCheck}>有额度才提交，只提交一次</Feature>
              </>
            ) : (
              <>
                <Feature icon={Clock}>冷启动提前量在布防表单中选择</Feature>
                <Feature icon={Zap}>默认开售 +200ms 首次查询，最多再重试 5 次</Feature>
                <Feature icon={ShieldCheck}>只提交一次，失败不重试</Feature>
              </>
            )}
            {ended && <p className="text-[10px] text-muted">上次任务已结束 · {phaseName(w.phase)}</p>}
          </>
        )}
      </ModeCard>
    )
  }

  return (
    <div className="grid h-full grid-rows-[repeat(3,minmax(180px,1fr))] gap-3.5 overflow-y-auto px-[26px]">
      {modeCard('first_launch')}
      {modeCard('redemption')}
      <ModeCard
        testId="mode-pickup"
        icon={Repeat}
        tone="blue"
        title="捡漏模式"
        subtitle="正在开发"
        badge={['正在做', 'warn']}
        actions={<Button disabled>敬请期待</Button>}
      >
        <Blurb>白天轮询多只理财，有人撤单、额度重新放出时自动买入。</Blurb>
        {['反复查看多只理财', '按可购额度比例买入', '白天运行，可设终止时间'].map((text) => (
          <Feature key={text} icon={Hammer}>
            {text}
          </Feature>
        ))}
      </ModeCard>
      <ArmDialog
        open={armMode !== null}
        onOpenChange={() => setArmMode(null)}
        mode={armMode ?? 'first_launch'}
      />
      <Confirm
        open={confirmDisarm}
        onOpenChange={setConfirmDisarm}
        title="取消当前布防？"
        message="取消后本轮不会再提交；已经发生的交易仍要查交易记录。"
        cancel="继续值守"
        confirm="确认取消"
        onConfirm={() => action('取消布防', () => api('POST', '/api/disarm'))}
      />
    </div>
  )
}

function ActiveSummary({ redemption }: { redemption: boolean }) {
  const w = useWatch()
  const task = w.task ?? {}
  return (
    <div className="flex flex-col gap-[7px]">
      <span className="font-rounded font-semibold text-[17px]">
        {task.code ?? '—'} · {task.amount ?? '—'} 元
      </span>
      <Blurb>
        {redemption
          ? `窗口 ${shortTime(task.at)} 起 ${task.window_minutes ?? 3} 分钟`
          : `开售 ${shortTime(task.at)}`}
      </Blurb>
      <div className="flex gap-3">
        <Metric title="最近心跳" value={ageText(w.status?.last_tick_age_s)} />
        <Metric title="图案输入" value={`${task.patterns_sent ?? 0} 次`} />
      </div>
      {w.phase === 'waiting' && <p className="text-[10px] text-muted">同一购买页等待与查询；还没有提交。</p>}
      {w.phase === 'firing' && !w.running && (
        <p className="text-[10px] text-accent">提交中进程已退出：先查交易记录，不要补单或重试。</p>
      )}
    </div>
  )
}

function ModeCard({
  icon,
  tone,
  title,
  subtitle,
  badge,
  actions,
  children,
  testId,
}: {
  icon: LucideIcon
  tone: Tone
  title: string
  subtitle: string
  badge: [string, Tone]
  actions: ReactNode
  children: ReactNode
  testId: string
}) {
  return (
    <section
      data-testid={testId}
      className="flex min-h-0 items-center gap-[18px] rounded-[14px] bg-card p-5 transition-colors duration-150 hover:bg-card-hover"
    >
      <IconTile icon={icon} tone={tone} />
      <div className="flex min-w-0 flex-1 flex-col gap-[7px] self-stretch overflow-y-auto py-0.5 [justify-content:safe_center]">
        <h2 className="font-semibold text-[17px]">{title}</h2>
        <p className="text-[11px] text-muted">{subtitle}</p>
        {children}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-[9px]">
        <Badge tone={badge[1]}>{badge[0]}</Badge>
        {actions}
      </div>
    </section>
  )
}

function Blurb({ children }: { children: ReactNode }) {
  return <p className="text-[11px] text-muted leading-snug">{children}</p>
}

function Feature({ icon: Icon, children }: { icon: LucideIcon; children: ReactNode }) {
  return (
    <div className="flex items-center gap-[7px] text-[11px] text-muted">
      <Icon className="size-2.5 shrink-0" strokeWidth={2.5} />
      <span>{children}</span>
    </div>
  )
}
