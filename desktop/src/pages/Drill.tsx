import { useQuery } from '@tanstack/react-query'
import { Copy, Minus, Plus } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { q, useAction, useRefreshPage, useWatch } from '../api/hooks'
import type { CancelRequest, CommandResult } from '../api/types'
import { ArmDialog } from '../components/ArmDialog'
import { FavoritePicker, LogText } from '../components/shared'
import { Button } from '../components/ui/button'
import { Card, Hint, Metric, MetricGrid } from '../components/ui/card'
import { Dialog } from '../components/ui/dialog'
import { Checkbox, Field, Input, Switch } from '../components/ui/form'
import { copyText, formatAmount, testItemText, validAmount, validCode } from '../lib/utils'
import { useUI } from '../store'
import { deviceFacts, useDeviceAction, useScreenshot } from './Dashboard'

const COMMANDS = [
  'python3 -B src/night_watch.py status',
  'python3 -B src/night_watch.py disarm',
  'python3 -B src/cancel_orders.py --list',
  'python3 -B src/fast_buy_uia2.py --code <代码> --amount <金额> --dry-run',
]

export function DrillPage() {
  const w = useWatch()
  const busy = useUI((s) => s.busy)
  const output = useUI((s) => s.commandOutput)
  const action = useAction()
  const deviceAction = useDeviceAction()
  const refresh = useRefreshPage()
  const shoot = useScreenshot()
  const { data: device } = useQuery(q.device)
  const d = deviceFacts(device)

  const [code, setCode] = useState('')
  const [amount, setAmount] = useState('0.01')
  const [realBuy, setRealBuy] = useState(false)
  const [cancelAmount, setCancelAmount] = useState('0.01')
  const [limit, setLimit] = useState(1)
  const [allOrders, setAllOrders] = useState(false)
  const [sheet, setSheet] = useState<'arm' | 'output' | 'cancel' | 'buy' | null>(null)
  const [confirmBuy, setConfirmBuy] = useState(false)
  const close = (open: boolean) => !open && setSheet(null)
  const canBuy = validCode(code) && validAmount(amount)
  const { testItem } = w
  const testItemUsed = useRef(false)

  // Open with the saved test item so a drill never has to look up product and
  // amount again; an already typed value wins.
  useEffect(() => {
    if (testItemUsed.current || !testItem) return
    testItemUsed.current = true
    setCode((value) => value.trim() || testItem.code)
    setAmount((value) => (value.trim() === '' || value === '0.01' ? testItem.amount : value))
  }, [testItem])

  async function buy(real: boolean) {
    useUI.getState().setOutput([])
    const result = await action(real ? '真实单笔购买' : '单笔购买演练', () =>
      api<CommandResult>('POST', '/api/buy', { code: code.trim(), amount, real }),
    )
    if (result) {
      useUI.getState().setOutput(result.output ?? [])
      setSheet('output')
    }
  }

  async function cancel(kind: CancelRequest['action']) {
    if (!validAmount(cancelAmount)) return
    useUI.getState().setOutput([])
    const body: CancelRequest = { amount: cancelAmount, limit: allOrders ? 0 : limit, action: kind }
    const result = await action(
      kind === 'list' ? '查看可撤单' : kind === 'dry_run' ? '撤单演练' : '真实撤单',
      () => api<CommandResult>('POST', '/api/cancel', body),
    )
    if (result) useUI.getState().setOutput(result.output ?? [])
  }

  return (
    <div className="grid auto-rows-min grid-cols-2 gap-3.5 overflow-y-auto px-[26px] pb-2">
      <Card title="演练布防" subtitle="走完整冷启动、登录、购买流程">
        <div className="flex flex-col gap-3">
          <Hint>
            默认输完交易密码后停在「确定」前，也可选择实际付款并确认金额；支持立即开始或指定开售时间。
          </Hint>
          <Button
            variant="primary"
            className="self-start"
            disabled={busy || w.active}
            onClick={() => setSheet('arm')}
          >
            打开演练布防
          </Button>
          <div className="h-px bg-white/5" />
          <span className="font-medium text-xs">单笔购买演练</span>
          <div className="flex gap-2.5">
            <Field label="产品代码">
              <Input placeholder="如 JX040229" value={code} onChange={(e) => setCode(e.target.value)} />
            </Field>
            <Field label="金额">
              <Input placeholder="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} />
            </Field>
          </div>
          <FavoritePicker
            onPick={(row) => {
              setCode(row.code)
              if (row.test_amount) setAmount(row.test_amount)
            }}
          />
          {testItem && (
            <Hint className="text-[10px]">
              测试项（来自收藏）：{testItemText(testItem)}；打开时自动填入，可直接修改。
            </Hint>
          )}
          <Switch
            label="实际付款：输入交易密码并提交"
            checked={realBuy}
            disabled={busy || w.active}
            onChange={setRealBuy}
          />
          <Hint tone={realBuy ? 'warn' : 'muted'}>
            {realBuy
              ? '立即购买一笔，不创建值守任务；下一步需确认金额。'
              : '输完交易密码后停在「确定」前，不点确定、不提交。'}
          </Hint>
          <div className="flex gap-2">
            <Button
              disabled={busy || w.active || !canBuy}
              onClick={() => {
                if (!realBuy) return buy(false)
                setConfirmBuy(false)
                setSheet('buy')
              }}
            >
              {realBuy ? '直接购买…' : '单笔购买演练'}
            </Button>
            <Button onClick={() => setSheet('output')}>命令输出</Button>
          </div>
        </div>
      </Card>

      <Card title="设备操作" subtitle="只操作项目专用模拟器">
        <MetricGrid>
          <Metric title="模拟器" value={d.known ? (d.running ? '运行中' : '未运行') : '尚未刷新'} />
          <Metric
            title="开机"
            value={d.known ? (d.running ? (d.booted ? '已完成' : '未完成') : '未运行') : '尚未刷新'}
          />
          <Metric title="App 进程" value={d.running ? d.appPid : '—'} />
          <Metric title="画面" value={d.running ? (d.awake ? 'Awake' : '未知') : '—'} />
        </MetricGrid>
        <div className="mt-1.5 flex flex-col gap-2">
          <div className="flex gap-2">
            <Button
              disabled={busy || w.active}
              onClick={() => deviceAction('启动模拟器', '/api/emulator/start')}
            >
              启动
            </Button>
            <Button
              disabled={busy || w.active}
              onClick={() => deviceAction('关闭模拟器', '/api/emulator/stop')}
            >
              关闭
            </Button>
            <Button disabled={busy} onClick={() => deviceAction('恢复常亮', '/api/keep-awake')}>
              恢复常亮
            </Button>
          </div>
          <div className="flex gap-2">
            <Button disabled={busy} onClick={shoot}>
              截图
            </Button>
            <Button disabled={busy} onClick={() => refresh('/drill')}>
              刷新设备
            </Button>
          </div>
          {w.active && <Hint className="text-[10px]">值守活动期间不能启动或关闭模拟器。</Hint>}
        </div>
      </Card>

      <Card title="撤单" subtitle="处理交易记录里可撤单的测试订单">
        <div className="flex flex-col gap-3">
          <Hint>先查看可撤单数量，再决定演练或真实撤单。真实撤单会输入交易密码并提交。</Hint>
          <div className="flex gap-2.5">
            <Field label="订单金额">
              <Input
                placeholder="0.01"
                value={cancelAmount}
                onChange={(e) => setCancelAmount(e.target.value)}
              />
            </Field>
            <div className="flex flex-1 flex-col gap-2">
              <span className="text-[11px] text-muted">最多撤几笔</span>
              <div
                className={
                  allOrders
                    ? 'flex h-[38px] items-center gap-2 opacity-45'
                    : 'flex h-[38px] items-center gap-2'
                }
              >
                <span className="min-w-[72px] text-[13px]">{allOrders ? '全部' : `最多 ${limit} 笔`}</span>
                <Button
                  size="icon"
                  aria-label="减少"
                  disabled={allOrders || limit <= 1}
                  onClick={() => setLimit(limit - 1)}
                >
                  <Minus className="size-3" />
                </Button>
                <Button
                  size="icon"
                  aria-label="增加"
                  disabled={allOrders || limit >= 20}
                  onClick={() => setLimit(limit + 1)}
                >
                  <Plus className="size-3" />
                </Button>
              </div>
            </div>
          </div>
          <Switch label="全部可撤单（不限笔数）" checked={allOrders} onChange={setAllOrders} />
          <div className="flex gap-2">
            <Button disabled={busy || w.active || !validAmount(cancelAmount)} onClick={() => cancel('list')}>
              查看可撤单
            </Button>
            <Button
              disabled={busy || w.active || !validAmount(cancelAmount)}
              onClick={() => cancel('dry_run')}
            >
              撤单演练
            </Button>
            <Button
              variant="primary"
              disabled={busy || w.active || !validAmount(cancelAmount)}
              onClick={() => setSheet('cancel')}
            >
              真实撤单
            </Button>
          </div>
          {w.active && (
            <Hint tone="warn" className="text-[10px]">
              值守活动期间不能撤单；先取消当前布防。
            </Hint>
          )}
          <div className="flex items-center">
            <Hint className="flex-1 text-[10px]">结果不明时先查交易记录，不要重复撤单。</Hint>
            <Button onClick={() => setSheet('output')}>查看输出</Button>
          </div>
        </div>
      </Card>

      <Card title="常用命令" subtitle="终端里的等价入口，可直接复制">
        <div className="flex flex-col gap-2.5">
          {COMMANDS.map((text) => (
            <div key={text} className="flex items-center gap-2">
              <code className="selectable flex-1 truncate font-mono text-[#c7c7c7] text-[10px]">{text}</code>
              <Button variant="ghost" size="icon" aria-label="复制命令" onClick={() => copyText(text)}>
                <Copy className="size-3" />
              </Button>
            </div>
          ))}
          <Hint className="mt-1.5 text-[10px]">真实布防、撤单和凭据修改须经用户明确确认后执行。</Hint>
        </div>
      </Card>

      <ArmDialog open={sheet === 'arm'} onOpenChange={close} drill />
      <Dialog
        open={sheet === 'output'}
        onOpenChange={close}
        title="命令输出"
        width={760}
        height={560}
        actions={
          <Button disabled={!output.length} onClick={() => copyText(output.join('\n'))}>
            复制
          </Button>
        }
      >
        {output.length ? (
          <LogText lines={output} className="flex-1 rounded-lg bg-field p-2.5" />
        ) : (
          <p className="flex-1 text-muted text-xs">运行演练、购买演练或撤单命令后，这里显示文本输出。</p>
        )}
        <Hint className="text-[10px]">撤单结果以银行交易记录为准；结果不明时不要重试。</Hint>
      </Dialog>
      <Dialog open={sheet === 'cancel'} onOpenChange={close} title="确认真实撤单" width={460}>
        <p className="text-[13px] leading-relaxed">
          金额 {cancelAmount} 元的可撤单订单，最多撤 {allOrders ? '全部' : limit}{' '}
          笔。会输入交易密码并提交，操作后立即查交易记录。
        </p>
        <Hint tone="accent">一笔只提交一次；结果不明时不要重试。</Hint>
        <div className="flex justify-end gap-2.5">
          <Button onClick={() => setSheet(null)}>取消</Button>
          <Button
            variant="primary"
            onClick={() => {
              setSheet(null)
              cancel('real')
            }}
          >
            确认撤单
          </Button>
        </div>
      </Dialog>
      <Dialog open={sheet === 'buy'} onOpenChange={close} title="确认真实单笔购买" width={480}>
        <div
          data-testid="confirm-buy-price"
          className="flex flex-col items-center gap-1 rounded-xl bg-field px-4 py-4 text-center ring-1 ring-white/6"
        >
          <span className="text-[11px] text-muted">本次真实支付金额</span>
          <span className="font-rounded font-semibold text-[38px] leading-none tracking-tight">
            <span className="mr-0.5 align-top text-[18px] text-muted">¥</span>
            {formatAmount(amount)}
          </span>
          <span className="mt-1.5 text-[11px] text-muted">{code.trim() || '—'} · 立即购买一笔</span>
        </div>
        <p className="text-[11px] leading-relaxed text-muted">将输入交易密码并提交一次，不创建值守任务。</p>
        <Checkbox
          testId="confirm-buy-check"
          checked={confirmBuy}
          onChange={setConfirmBuy}
          label={`我已核对产品、金额和时间，确认真实支付 ¥${formatAmount(amount)}`}
        />
        <Hint tone="warn">结果以银行交易记录为准；结果不明时先核对，不要重复购买。</Hint>
        <div className="flex justify-end gap-2.5">
          <Button onClick={() => setSheet(null)}>取消</Button>
          <Button
            variant="primary"
            disabled={busy || w.active || !confirmBuy}
            onClick={() => {
              setSheet(null)
              buy(true)
            }}
          >
            确认实际付款
          </Button>
        </div>
      </Dialog>
    </div>
  )
}
