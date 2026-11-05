import '@xyflow/react/dist/style.css'
import { type Edge, Handle, MarkerType, type Node, type NodeProps, Position, ReactFlow } from '@xyflow/react'
import { CircleHelp, Undo2 } from 'lucide-react'
import { createContext, type ReactNode, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { cn } from '../lib/utils'
import { Badge } from './ui/card'

/**
 * How a number behaves at run time. `limit` is only a bound: the code polls a
 * condition and moves on the moment it holds, so the value is never added to
 * the purchase time. `fixed` is a literal sleep in the adb command list and is
 * added every time.
 */
type Kind = 'limit' | 'fixed'
const KIND: Record<Kind, { label: string; tone: 'warn' | 'blue' }> = {
  limit: { label: '限度', tone: 'warn' },
  fixed: { label: '固定', tone: 'blue' },
}

/** The values that live on the P8 → P12 flow. */
export type FlowKey =
  | 'password_page_timeout_s'
  | 'keypad_timeout_ms'
  | 'keypad_stable_ms'
  | 'keypad_stable_samples'
  | 'keypad_sample_gap_ms'
  | 'password_same_digit_gap_ms'
  | 'password_different_digit_gap_ms'
  | 'password_confirm_gap_ms'
  | 'password_done_gap_ms'
  | 'password_retry_gap_ms'
  | 'password_close_wait_ms'
  | 'password_confirm_timeout_ms'
  | 'result_first_wait_ms'
  | 'result_timeout_s'

const META: Record<FlowKey, { name: string; unit: '毫秒' | '秒' | '次'; kind: Kind; detail: string }> = {
  password_page_timeout_s: {
    name: '等密码面板',
    unit: '秒',
    kind: 'limit',
    detail:
      '风险确认后轮询密码页文案，面板一出现就继续，这个值不会拖慢流程。调大只在银行慢时少一次中止，调小可能把「还没出来」误判成失败。',
  },
  keypad_timeout_ms: {
    name: '等键盘就绪',
    unit: '毫秒',
    kind: 'limit',
    detail:
      '轮询密码框焦点和 10 个数字键，满足就立即输入，是等待上限；等不到会停止，绝不在不稳定的键盘上盲点。',
  },
  keypad_stable_ms: {
    name: '键盘稳定',
    unit: '毫秒',
    kind: 'limit',
    detail:
      '判定下限：键盘位置连续不动达到这么久才认为就绪（不是固定等待，就绪即输入）。调小可能点到动画中的坐标，调大只多等一会儿。',
  },
  keypad_stable_samples: {
    name: '稳定采样次数',
    unit: '次',
    kind: 'limit',
    detail:
      '判定下限：除了稳定时长，还要连续这么多次读到相同的键盘位置才算就绪。每读一次控件树约 0.1 秒，所以 3 次大约在 200ms 处凑齐；调大会推迟就绪。',
  },
  keypad_sample_gap_ms: {
    name: '采样间隔',
    unit: '毫秒',
    kind: 'fixed',
    detail:
      '两次读控件树之间额外 sleep 多久。读一次本身约 0.1 秒，已经是天然节拍，所以默认 0；原来是 40ms，会让第 3 次采样拖到约 280ms，每次都多等这一截。',
  },
  password_same_digit_gap_ms: {
    name: '相同数字间隔',
    unit: '毫秒',
    kind: 'fixed',
    detail:
      '同一位数字连按会被 App 合并成一位（11-20 次里 5 次只进 5 位），所以按同一个键前固定等这么久，直接累加进提交耗时。',
  },
  password_different_digit_gap_ms: {
    name: '不同数字间隔',
    unit: '毫秒',
    kind: 'fixed',
    detail: '不同数字的坐标不同，不需要长间隔；5 次相加就是这 5 段的总耗时。',
  },
  password_confirm_gap_ms: {
    name: '输完到点确定',
    unit: '毫秒',
    kind: 'fixed',
    detail: '最后一位输完后固定等这么久再点「确定」，给按钮状态留出刷新时间，直接计入提交耗时。',
  },
  password_done_gap_ms: {
    name: '点完成后等待',
    unit: '毫秒',
    kind: 'fixed',
    detail: '「确定」被键盘挡住时改点「完成」，之后固定等这么久再读一次状态；只在走「完成」兜底时产生。',
  },
  password_retry_gap_ms: {
    name: '清空重输前',
    unit: '毫秒',
    kind: 'fixed',
    detail: '确定仍不可用时，点密码框清空输入，固定等这么久再重输；只在重输分支产生，且只重试一次。',
  },
  password_close_wait_ms: {
    name: '关闭密码框后',
    unit: '毫秒',
    kind: 'fixed',
    detail:
      '关闭密码框、丢弃已输数字后固定等这么久；演练结束和失败停止两条路径共用，真实提交成功后不需要关闭。',
  },
  password_confirm_timeout_ms: {
    name: '等确定可用',
    unit: '毫秒',
    kind: 'limit',
    detail: '六位输完后轮询「确定」是否可点，可点就立即点，是等不到时的上限；超时才会清空重输。',
  },
  result_first_wait_ms: {
    name: '点确定后读结果',
    unit: '毫秒',
    kind: 'fixed',
    detail: '点确定后固定等这么久再开始识别结果页，避开页面切换动画，直接计入提交后的耗时。',
  },
  result_timeout_s: {
    name: '结果页上限',
    unit: '秒',
    kind: 'limit',
    detail: '识别结果页的最长等待，命中即结束，不会真的等满；超时记「结果未知」，请以银行交易记录为准。',
  },
}

type Outcome = { kind: 'loop' | 'stop' | 'end'; text: string }

type FlowNodeData = {
  tag?: string
  title: string
  values: FlowKey[]
  branch?: boolean
  outcome?: Outcome
  fork?: boolean
  loop?: boolean
}

type Step = { id: string; tag: string; title: string; values: FlowKey[] }
type BranchStep = { id: string; title: string; values: FlowKey[]; outcome: Outcome }

const MAIN: Step[] = [
  { id: 'p8', tag: 'P8', title: '购买表单已就绪', values: [] },
  { id: 'p9', tag: 'P9', title: '复核并写入提交标记', values: [] },
  { id: 'p10', tag: 'P10', title: '风险确认', values: [] },
  { id: 'p11-1', tag: 'P11.1', title: '密码面板弹出', values: ['password_page_timeout_s'] },
  {
    id: 'p11-2',
    tag: 'P11.2',
    title: '键盘就绪',
    values: ['keypad_timeout_ms', 'keypad_stable_ms', 'keypad_stable_samples', 'keypad_sample_gap_ms'],
  },
  {
    id: 'p11-3',
    tag: 'P11.3',
    title: '逐位输入 6 位',
    values: ['password_same_digit_gap_ms', 'password_different_digit_gap_ms'],
  },
  { id: 'p11-4', tag: 'P11.4', title: '点确定前', values: ['password_confirm_gap_ms'] },
  { id: 'p11-5', tag: 'P11.5', title: '判断「确定」', values: ['password_confirm_timeout_ms'] },
  { id: 'p11-6', tag: 'P11.6', title: '点「确定」= 提交', values: [] },
  { id: 'p12', tag: 'P12', title: '读结果', values: ['result_first_wait_ms', 'result_timeout_s'] },
]

const BRANCHES: BranchStep[] = [
  {
    id: 'b-done',
    title: '被键盘挡住',
    values: ['password_done_gap_ms'],
    outcome: { kind: 'loop', text: '回到 P11.5' },
  },
  {
    id: 'b-retry',
    title: '未遮挡但不可用',
    values: ['password_retry_gap_ms'],
    outcome: { kind: 'loop', text: '回到 P11.2' },
  },
  {
    id: 'b-stop',
    title: '仍不可用 / 读不到',
    values: ['password_close_wait_ms'],
    outcome: { kind: 'stop', text: '停止 · 不提交' },
  },
  {
    id: 'b-drill',
    title: '演练',
    values: [],
    outcome: { kind: 'end', text: '结束 · 未提交' },
  },
]

// Fixed sizes keep the layout deterministic: no measuring, no reflow while typing.
const MAIN_W = 336
const BRANCH_W = 300
const GUTTER = 64
const X_BRANCH = MAIN_W + GUTTER
const DESIGN_W = X_BRANCH + BRANCH_W
const GAP = 40
const BRANCH_GAP = 56
const HEAD = 38
const valueArea = (count: number) => (count === 0 ? 0 : 6 + count * 26 + (count - 1) * 6)
const nodeHeight = (count: number) => HEAD + valueArea(count)

function buildGraph(): { nodes: Node<FlowNodeData>[]; edges: Edge[]; height: number } {
  const nodes: Node<FlowNodeData>[] = []
  const edges: Edge[] = []
  const pos: Record<string, number> = {}

  // Spine first (P11.6 and P12 are placed after the fork stack so it fits).
  let y = 0
  for (const step of MAIN) {
    if (step.id === 'p11-6' || step.id === 'p12') continue
    pos[step.id] = y
    y += nodeHeight(step.values.length) + GAP
  }

  const p5 = pos['p11-5']
  pos['b-done'] = p5
  pos['b-retry'] = p5 + nodeHeight(1) + BRANCH_GAP
  pos['b-stop'] = pos['b-retry'] + nodeHeight(1) + BRANCH_GAP
  const afterFork = Math.max(p5 + nodeHeight(1), pos['b-stop'] + nodeHeight(1)) + GAP
  pos['p11-6'] = afterFork
  pos['b-drill'] = afterFork
  pos['p12'] = afterFork + HEAD + GAP
  pos['end'] = pos['p12'] + nodeHeight(2) + GAP

  MAIN.forEach((step) => {
    nodes.push({
      id: step.id,
      type: 'flow',
      position: { x: 0, y: pos[step.id] },
      data: {
        tag: step.tag,
        title: step.title,
        values: step.values,
        fork: step.id === 'p11-5' || step.id === 'p11-6',
        loop: step.id === 'p11-2' || step.id === 'p11-5',
      },
      style: { width: MAIN_W, height: nodeHeight(step.values.length), pointerEvents: 'all' },
    })
  })
  nodes.push({
    id: 'end',
    type: 'flow',
    position: { x: 0, y: pos['end'] },
    data: { title: '结束 · 以银行交易记录为准', values: [] },
    style: { width: MAIN_W, height: HEAD, pointerEvents: 'all' },
  })
  BRANCHES.forEach((step) => {
    nodes.push({
      id: step.id,
      type: 'flow',
      position: { x: X_BRANCH, y: pos[step.id] },
      data: {
        title: step.title,
        values: step.values,
        branch: true,
        outcome: step.outcome,
        loop: step.outcome.kind === 'loop',
      },
      style: { width: BRANCH_W, height: nodeHeight(step.values.length), pointerEvents: 'all' },
    })
  })

  const chain = ['p8', 'p9', 'p10', 'p11-1', 'p11-2', 'p11-3', 'p11-4', 'p11-5', 'p11-6', 'p12', 'end']
  for (let i = 1; i < chain.length; i += 1) edges.push(edge(chain[i - 1], chain[i], 'main', 'bottom', 'top'))

  edges.push(edge('p11-5', 'b-done', 'fork', 'fork', 'in'))
  edges.push(edge('p11-5', 'b-retry', 'fork', 'fork', 'in'))
  edges.push(edge('p11-5', 'b-stop', 'fork', 'fork', 'in'))
  edges.push(edge('p11-6', 'b-drill', 'fork', 'fork', 'in'))
  edges.push(edge('b-done', 'p11-5', 'loop', 'loop', 'loop'))
  edges.push(edge('b-retry', 'p11-2', 'loop', 'loop', 'loop'))

  return { nodes, edges, height: pos['end'] + HEAD }
}

const STROKE = {
  main: '#4b4b53',
  fork: '#8a6a3a',
  loop: '#3f5f8a',
} as const

function edge(
  source: string,
  target: string,
  kind: 'main' | 'fork' | 'loop',
  sourceHandle: string,
  targetHandle: string,
): Edge {
  const color = STROKE[kind]
  return {
    id: `${source}-${target}`,
    source,
    target,
    sourceHandle,
    targetHandle,
    type: 'smoothstep',
    ...(kind === 'loop' ? { pathOptions: { offset: 46 } } : {}),
    style: {
      stroke: color,
      strokeWidth: 1.4,
      strokeDasharray: kind === 'loop' ? '5 4' : undefined,
    },
    markerEnd: { type: MarkerType.ArrowClosed, width: 13, height: 13, color },
  } as Edge
}

type FlowContext = {
  field: (key: string, unit: string, label: string) => ReactNode
  errors: Record<string, string | undefined>
  limits: Record<string, [number, number]>
}

const FlowCtx = createContext<FlowContext | null>(null)
const useFlow = () => {
  const value = useContext(FlowCtx)
  if (!value) throw new Error('PurchaseFlow must wrap its nodes')
  return value
}

/** Tooltip in a portal so the canvas never clips it. */
function Tip({ text }: { text: string }) {
  const ref = useRef<HTMLButtonElement>(null)
  const [at, setAt] = useState<{ x: number; y: number } | null>(null)
  const open = () => {
    const box = ref.current?.getBoundingClientRect()
    if (box) setAt({ x: box.right, y: box.bottom })
  }
  return (
    <>
      <button
        ref={ref}
        type="button"
        aria-label="查看这个值的说明"
        onMouseEnter={open}
        onFocus={open}
        onMouseLeave={() => setAt(null)}
        onBlur={() => setAt(null)}
        className="inline-flex size-4 shrink-0 cursor-help items-center justify-center rounded-full text-muted/60 transition-colors hover:text-fg focus-visible:text-fg"
      >
        <CircleHelp className="size-3" strokeWidth={2.2} />
      </button>
      {at
        ? createPortal(
            <div
              role="tooltip"
              style={{ left: at.x, top: at.y + 6, transform: 'translateX(-100%)' }}
              className="pointer-events-none fixed z-[9999] w-[252px] rounded-lg border border-white/10 bg-[#17171a] p-2.5 text-[11px] leading-relaxed text-muted shadow-2xl"
            >
              {text}
            </div>,
            document.body,
          )
        : null}
    </>
  )
}

function OutcomeChip({ outcome }: { outcome: Outcome }) {
  const tone = outcome.kind === 'loop' ? 'text-blue' : outcome.kind === 'stop' ? 'text-accent' : 'text-muted'
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded-full border border-white/10 px-1.5 py-[2px] text-[9.5px]',
        tone,
      )}
    >
      {outcome.kind === 'loop' ? <Undo2 className="size-2.5" strokeWidth={2.6} /> : null}
      {outcome.text}
    </span>
  )
}

function FlowNode({ data }: NodeProps) {
  const node = data as FlowNodeData
  const { field, limits } = useFlow()
  return (
    <div
      className={cn(
        'flex h-full w-full flex-col rounded-xl border bg-[#151518] px-2.5 py-2',
        node.branch ? 'border-white/10' : 'border-white/15',
      )}
    >
      <div className="flex items-center gap-1.5">
        {node.tag ? <span className="shrink-0 text-[10px] text-muted tabular-nums">{node.tag}</span> : null}
        <span className="min-w-0 flex-1 truncate text-[11.5px] font-medium">{node.title}</span>
        {node.outcome ? <OutcomeChip outcome={node.outcome} /> : null}
      </div>

      {node.values.length > 0 ? (
        <div className="mt-1.5 flex flex-col gap-1.5">
          {node.values.map((key) => {
            const meta = META[key]
            const [lo, hi] = limits[key] ?? [0, 0]
            return (
              <div key={key} className="flex items-center gap-1.5">
                <span className="min-w-0 flex-1 truncate text-[10.5px] text-fg/80">{meta.name}</span>
                <Badge tone={KIND[meta.kind].tone}>{KIND[meta.kind].label}</Badge>
                <div className="w-[88px] shrink-0">{field(key, meta.unit, meta.name)}</div>
                <Tip text={`${meta.detail} 可设 ${lo}–${hi} ${meta.unit}。`} />
              </div>
            )
          })}
        </div>
      ) : null}

      {/* Invisible handles: this graph is static, only its shape matters. */}
      {node.branch ? (
        <>
          <Handle id="in" type="target" position={Position.Left} style={{ opacity: 0 }} />
          {node.loop ? (
            <Handle id="loop" type="source" position={Position.Left} style={{ opacity: 0, top: '86%' }} />
          ) : null}
        </>
      ) : (
        <>
          <Handle id="top" type="target" position={Position.Top} style={{ opacity: 0 }} />
          <Handle id="bottom" type="source" position={Position.Bottom} style={{ opacity: 0 }} />
          {node.fork ? (
            <Handle id="fork" type="source" position={Position.Right} style={{ opacity: 0, top: '42%' }} />
          ) : null}
          {node.loop ? (
            <Handle id="loop" type="target" position={Position.Right} style={{ opacity: 0, top: '86%' }} />
          ) : null}
        </>
      )}
    </div>
  )
}

const NODE_TYPES = { flow: FlowNode }

export function PurchaseFlow({
  field,
  errors,
  limits,
}: {
  field: (key: string, unit: string, label: string) => ReactNode
  errors: Record<string, string | undefined>
  limits: Record<string, [number, number]>
}) {
  const graph = useMemo(buildGraph, [])
  const context = useMemo(() => ({ field, errors, limits }), [field, errors, limits])
  const box = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(1)
  // The diagram has a fixed design width; shrink it (never stretch) to fit the
  // card instead of crushing the columns together on a narrow window.
  useEffect(() => {
    const el = box.current
    if (!el) return
    const fit = () => setScale(Math.min(1, el.clientWidth / DESIGN_W))
    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  return (
    <FlowCtx.Provider value={context}>
      <div ref={box} style={{ height: graph.height * scale, width: '100%' }}>
        <div
          style={{
            width: DESIGN_W,
            height: graph.height,
            transform: `scale(${scale})`,
            transformOrigin: 'top left',
          }}
        >
          <ReactFlow
            nodes={graph.nodes}
            edges={graph.edges}
            nodeTypes={NODE_TYPES}
            fitView={false}
            defaultViewport={{ x: 0, y: 0, zoom: 1 }}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            zoomOnScroll={false}
            zoomOnPinch={false}
            zoomOnDoubleClick={false}
            panOnDrag={false}
            panOnScroll={false}
            preventScrolling={false}
            nodesFocusable={false}
            edgesFocusable={false}
            proOptions={{ hideAttribution: true }}
          />
        </div>
      </div>
    </FlowCtx.Provider>
  )
}
