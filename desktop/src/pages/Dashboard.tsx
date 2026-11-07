import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Camera, FileText, Image, KeyRound, Laptop, ShieldHalf, Smartphone } from 'lucide-react'
import { useState } from 'react'
import { api, blobUrl } from '../api/client'
import { q, useAction, useRefreshPage, useWatch } from '../api/hooks'
import type { Device } from '../api/types'
import { LogDialog, LogPreview, LogText } from '../components/shared'
import { Button } from '../components/ui/button'
import { Badge, DashboardCard, Detail, Hint, Metric, MetricGrid, StatusDot } from '../components/ui/card'
import { Dialog } from '../components/ui/dialog'
import { ageText, copyText, phaseName, phaseTone, type Tone } from '../lib/utils'
import { useUI } from '../store'

const flag = (value: boolean | undefined, yes: Tone = 'good'): Tone | undefined =>
  value === undefined ? undefined : value ? yes : 'warn'

/** Screenshot action shared with the drill page: capture, then load the PNG. */
export function useScreenshot() {
  const action = useAction()
  return () =>
    action('截取画面', async () => {
      await api('POST', '/api/screenshot')
      useUI.getState().setScreenshot(await blobUrl('/api/screenshot.png'))
    })
}

/** Emulator start/stop/keep-awake: run it, then re-read the device card. */
export function useDeviceAction() {
  const action = useAction()
  const qc = useQueryClient()
  return (label: string, path: string) =>
    action(label, async () => {
      await api('POST', path)
      await qc.invalidateQueries({ queryKey: q.device.queryKey })
    })
}

export function deviceFacts(device: Device | undefined) {
  const running = device?.emulator?.running === true
  const pid = device?.app_pid ?? '—'
  return {
    known: device !== undefined,
    running,
    booted: device?.booted === true,
    appPid: pid === '-1' || pid === '' ? '未运行' : pid,
    awake: device?.awake,
  }
}

export function DashboardPage() {
  const w = useWatch()
  const busy = useUI((s) => s.busy)
  const screenshot = useUI((s) => s.screenshotUrl)
  const action = useAction()
  const navigate = useNavigate()
  const shoot = useScreenshot()
  const deviceAction = useDeviceAction()
  const refresh = useRefreshPage()
  const { data: device } = useQuery(q.device)
  const { data: system } = useQuery(q.system)
  const { data: info } = useQuery(q.info)
  const [sheet, setSheet] = useState<'sleep' | 'log' | 'shot' | 'emulator' | null>(null)
  const close = (open: boolean) => !open && setSheet(null)
  const d = deviceFacts(device)
  const logs = w.status?.logs ?? []

  const copyWatch = () => {
    if (info) copyText(`读取项目 Skill「${info.skill_path}」，用 cmb-watch 监听当前布防。`)
  }
  const lid = system?.clamshell?.includes('No')
    ? '已打开'
    : system?.clamshell?.includes('Yes')
      ? '已合盖'
      : system
        ? '无法读取'
        : '—'

  return (
    <div className="grid h-full grid-cols-2 grid-rows-[repeat(3,minmax(180px,1fr))] gap-4 overflow-y-auto px-[26px]">
      <DashboardCard
        testId="card-watch"
        title="值守"
        icon={ShieldHalf}
        footer={
          w.task ? (
            <>
              <Button disabled={busy} onClick={() => action('刷新状态', () => Promise.resolve())}>
                刷新
              </Button>
              <Button onClick={copyWatch}>复制监听指令</Button>
              <span className="flex-1" />
              {w.active && <Button onClick={() => navigate({ to: '/tasks' })}>去任务页</Button>}
            </>
          ) : (
            <Button onClick={() => navigate({ to: '/tasks' })}>去任务页</Button>
          )
        }
      >
        {w.task ? (
          <>
            <div className="flex items-center gap-2">
              <Badge tone={phaseTone(w.phase)}>{phaseName(w.phase)}</Badge>
              {w.task.dry_run && <Badge>演练</Badge>}
              <span className="flex-1" />
              <span className={w.running ? 'text-good text-[11px]' : 'text-warn text-[11px]'}>
                {w.running ? '运行中' : '未运行'}
              </span>
            </div>
            <MetricGrid>
              <Metric title="最近心跳" value={ageText(w.status?.last_tick_age_s)} />
              <Metric title="Agent" value={w.agentShort} />
              <Metric title="日志" value={`${logs.length} 行`} />
              <Metric
                title="值守进程"
                value={w.running ? '运行中' : '未运行'}
                tone={w.running ? 'good' : 'warn'}
              />
            </MetricGrid>
            {w.phase === 'firing' && !w.running && (
              <Hint tone="accent" className="text-[10px]">
                提交中进程已退出：先查交易记录，不要补单或重试。
              </Hint>
            )}
          </>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <StatusDot state={null} />
              <span className="font-medium text-xs">未布防</span>
            </div>
            <Hint>去任务页选择首发或不定时抢购模式布防。</Hint>
          </>
        )}
      </DashboardCard>

      <DashboardCard
        testId="card-mac"
        title="Mac"
        icon={Laptop}
        footer={
          <>
            <Button disabled={busy} onClick={() => refresh('/status')}>
              刷新
            </Button>
            <Button onClick={() => setSheet('sleep')}>休眠设置</Button>
            <span className="flex-1" />
            <span className="text-[9px] text-muted">只读</span>
          </>
        }
      >
        <MetricGrid>
          <Metric
            title="电源"
            value={system ? (system.on_ac ? '已接电源' : '电池供电') : '尚未刷新'}
            tone={flag(system?.on_ac)}
          />
          <Metric title="合盖" value={lid} />
          <Metric
            title="防休眠"
            value={system ? (system.watch_caffeinate ? '已声明' : '未声明') : '尚未刷新'}
            tone={flag(system?.watch_caffeinate)}
          />
          <Metric
            title="网络"
            value={
              typeof system?.network_s === 'number'
                ? `${system.network_s.toFixed(3)} 秒`
                : system
                  ? '异常'
                  : '尚未检查'
            }
            tone={flag(system?.network_ok)}
          />
        </MetricGrid>
      </DashboardCard>

      <DashboardCard
        testId="card-emulator"
        title="模拟器"
        icon={Smartphone}
        footer={
          <>
            <Button
              size="compact"
              disabled={busy || w.active}
              onClick={() => deviceAction('启动模拟器', '/api/emulator/start')}
            >
              启动
            </Button>
            <Button
              size="compact"
              disabled={busy || w.active}
              onClick={() => deviceAction('关闭模拟器', '/api/emulator/stop')}
            >
              关闭
            </Button>
            <Button
              size="compact"
              disabled={busy}
              onClick={() => deviceAction('恢复常亮', '/api/keep-awake')}
            >
              恢复常亮
            </Button>
            <Button size="compact" disabled={busy} onClick={shoot}>
              截图
            </Button>
            <span className="flex-1" />
            <Button size="compact" onClick={() => setSheet('emulator')}>
              详情
            </Button>
          </>
        }
      >
        <MetricGrid>
          <Metric
            title="运行"
            value={d.known ? (d.running ? '运行中' : '未运行') : '尚未刷新'}
            tone={d.known ? (d.running ? 'good' : 'warn') : undefined}
          />
          <Metric
            title="开机"
            value={d.known ? (d.running ? (d.booted ? '已完成' : '未完成') : '未运行') : '尚未刷新'}
          />
          <Metric title="App 进程" value={d.running ? d.appPid : '—'} />
          <Metric
            title="屏幕"
            value={!d.running || d.awake === undefined ? '—' : d.awake ? 'Awake' : '休眠'}
          />
          <Metric
            title="插电常亮"
            value={d.running ? (device?.stay_on === '15' ? '已开启' : '未开启') : '—'}
          />
          <Metric
            title="锁屏禁用"
            value={d.running ? (device?.lock_disabled === 'true' ? '已禁用' : '未禁用') : '—'}
          />
        </MetricGrid>
      </DashboardCard>

      <DashboardCard
        testId="card-screen"
        title="画面"
        icon={Camera}
        footer={
          <>
            <Button disabled={busy} onClick={shoot}>
              截图
            </Button>
            {screenshot && <Button onClick={() => setSheet('shot')}>放大</Button>}
            <span className="flex-1" />
            <span className="text-[9px] text-muted">仅本机</span>
          </>
        }
      >
        {screenshot ? (
          <button type="button" onClick={() => setSheet('shot')} className="flex justify-center">
            <img src={screenshot} alt="模拟器画面" className="max-h-[90px] rounded-lg object-contain" />
          </button>
        ) : (
          <div className="flex h-20 flex-col items-center justify-center gap-1.5 text-muted">
            <Image className="size-5" />
            <span className="text-[11px]">还没有截图</span>
          </div>
        )}
      </DashboardCard>

      <DashboardCard
        testId="card-credentials"
        title="凭据与通知"
        icon={KeyRound}
        footer={
          <>
            <Button onClick={() => navigate({ to: '/settings' })}>打开设置</Button>
            <span className="flex-1" />
            <span className="text-[9px] text-muted">不修改银行设置</span>
          </>
        }
      >
        <MetricGrid>
          <Metric
            title="登录与交易凭据"
            value={w.credentialState}
            tone={w.credentialState === '已设置' ? 'good' : 'warn'}
          />
          <Metric
            title="推送通知"
            value={w.pushConfigured ? '已配置' : '未配置'}
            tone={w.pushConfigured ? 'good' : undefined}
          />
        </MetricGrid>
      </DashboardCard>

      <DashboardCard
        testId="card-log"
        title="最近日志"
        icon={FileText}
        scrollBody={false}
        footer={
          <>
            <Button disabled={busy} onClick={() => setSheet('log')}>
              查看日志
            </Button>
            <span className="flex-1" />
            <span className="text-[9px] text-muted">最近 6 行</span>
          </>
        }
      >
        <LogPreview lines={logs} maxLines={6} testId="recent-log" className="text-[9px] leading-[1.5]" />
      </DashboardCard>

      <Dialog open={sheet === 'sleep'} onOpenChange={close} title="休眠设置" width={760} height={460}>
        <LogText lines={system?.sleep_settings?.split('\n') ?? ['未刷新']} className="flex-1" />
        <Hint className="text-[10px]">只读展示 pmset 输出，不修改 Mac 设置。</Hint>
      </Dialog>
      <LogDialog open={sheet === 'log'} onOpenChange={close} />
      <Dialog open={sheet === 'shot'} onOpenChange={close} title="模拟器画面" width={760} height={620}>
        {screenshot ? (
          <img src={screenshot} alt="模拟器画面" className="min-h-0 flex-1 object-contain" />
        ) : (
          <p className="text-muted">还没有截图</p>
        )}
      </Dialog>
      <Dialog open={sheet === 'emulator'} onOpenChange={close} title="模拟器详情" width={680} height={430}>
        <div className="grid grid-cols-3 gap-4">
          <Detail title="运行状态" value={d.running ? '运行中' : '未运行'} />
          <Detail title="开机状态" value={d.booted ? '已完成' : '未完成'} />
          <Detail title="分辨率" value={device?.resolution} />
          <Detail title="App 进程" value={d.appPid} />
          <Detail title="屏幕" value={d.awake === undefined ? '无法读取' : d.awake ? 'Awake' : '休眠'} />
          <Detail title="分辨率正确" value={device?.resolution_ok ? '是' : '否 / 无法读取'} />
          <Detail title="插电常亮" value={device?.stay_on} />
          <Detail
            title="模拟 AC"
            value={device?.ac_powered === undefined ? '无法读取' : device.ac_powered ? '已接通' : '未接通'}
          />
          <Detail title="熄屏时间" value={device?.screen_timeout} />
          <Detail title="锁屏禁用" value={device?.lock_disabled} />
        </div>
        <Hint className="text-[10px]">
          屏幕、常亮与模拟 AC 在模拟器重启后可能丢失，可回到状态页恢复常亮。
        </Hint>
      </Dialog>
    </div>
  )
}
