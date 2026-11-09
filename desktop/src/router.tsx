import { useQueryClient } from '@tanstack/react-query'
import {
  createHashHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Link,
  redirect,
  useRouterState,
} from '@tanstack/react-router'
import { CalendarClock, FlaskConical, Gauge, History, Layers, RotateCw, Settings, Star } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { q, useRefreshPage, useStatusEvents, useWatch } from './api/hooks'
import { Spinner } from './components/shared'
import { Toast } from './components/Toast'
import { Button } from './components/ui/button'
import { clockTime, cn } from './lib/utils'
import { DashboardPage } from './pages/Dashboard'
import { DrillPage } from './pages/Drill'
import { FavoritesPage } from './pages/Favorites'
import { HistoryPage } from './pages/History'
import { LivePage, WatchBubble } from './pages/Live'
import { PlanPage } from './pages/Plan'
import { SettingsPage } from './pages/Settings'
import { TasksPage } from './pages/Tasks'
import { useUI } from './store'

const PAGES = [
  {
    path: '/tasks',
    title: '任务',
    icon: Layers,
    subtitle: '三种购买模式',
    component: TasksPage,
    keepAlive: false,
  },
  {
    path: '/plan',
    title: '计划',
    icon: CalendarClock,
    subtitle: '计划模式 · 多个布防自动排程',
    component: PlanPage,
    // Draft rows and the timeline/week switch live only in the page, so this menu
    // must not be unmounted on the way out.
    keepAlive: true,
  },
  {
    path: '/status',
    title: '状态',
    icon: Gauge,
    subtitle: '运行环境与设备',
    component: DashboardPage,
    keepAlive: false,
  },
  {
    path: '/drill',
    title: '演练',
    icon: FlaskConical,
    subtitle: '测试命令与撤单',
    component: DrillPage,
    keepAlive: false,
  },
  {
    path: '/favorites',
    title: '收藏',
    icon: Star,
    subtitle: '常用产品代码',
    component: FavoritesPage,
    keepAlive: false,
  },
  {
    path: '/history',
    title: '历史',
    icon: History,
    subtitle: '完成情况与日志',
    component: HistoryPage,
    keepAlive: false,
  },
  {
    path: '/settings',
    title: '设置',
    icon: Settings,
    subtitle: '项目与凭据',
    component: SettingsPage,
    keepAlive: false,
  },
] as const

type PageDef = (typeof PAGES)[number]
type PagePath = PageDef['path']
const LAST_PAGE = 'last-page'

function lastPage(): PagePath {
  try {
    const saved = localStorage.getItem(LAST_PAGE)
    if (PAGES.some((p) => p.path === saved)) return saved as PagePath
  } catch {}
  return '/tasks'
}

/**
 * One menu page is active at a time. A page marked `keepAlive` is mounted on its
 * first visit and then only hidden while another menu is open, so its local state
 * survives the round trip; every other page still unmounts and starts fresh.
 * Page state belongs in the page component — opt in here instead of adding a store.
 */
function PageOutlet({ current }: { current: PageDef }) {
  const [kept, setKept] = useState<PagePath[]>([])

  useEffect(() => {
    if (!current.keepAlive) return
    setKept((paths) => (paths.includes(current.path) ? paths : [...paths, current.path]))
  }, [current])

  return (
    <>
      {PAGES.map((page) => {
        const active = page.path === current.path
        if (!active && !(page.keepAlive && kept.includes(page.path))) return null
        return (
          <div key={page.path} className={active ? 'flex min-h-0 flex-1 flex-col' : 'hidden'}>
            <page.component />
          </div>
        )
      })}
    </>
  )
}

function Layout() {
  useStatusEvents()
  const qc = useQueryClient()
  const { active } = useWatch()
  const path = useRouterState({ select: (s) => s.location.pathname })
  const page = PAGES.find((p) => p.path === path) ?? PAGES[0]
  // While a task is active the Tasks page becomes the focus view; other pages stay reachable.
  const live = active && page.path === '/tasks'

  useEffect(() => {
    try {
      localStorage.setItem(LAST_PAGE, path)
    } catch {}
  }, [path])

  // First status read before the event stream's first tick.
  useEffect(() => {
    qc.prefetchQuery(q.status)
  }, [qc])

  return (
    <div className="flex h-full">
      <Sidebar current={page.path} active={active} showBubble={active && !live} />
      <main className="relative flex min-w-0 flex-1 flex-col bg-bg">
        {/* The page stack stays mounted while the focus view is up, so coming back
            from it never resets keep-alive pages. */}
        <div className={live ? 'hidden' : 'flex min-h-0 flex-1 flex-col gap-[18px]'}>
          <Header title={page.title} subtitle={page.subtitle} path={page.path} />
          <div className="flex min-h-0 flex-1 flex-col pb-[26px]">
            <PageOutlet current={page} />
          </div>
        </div>
        {live && <LivePage />}
      </main>
      <Toast top={live ? 20 : 82} />
    </div>
  )
}

function Sidebar({ current, active, showBubble }: { current: string; active: boolean; showBubble: boolean }) {
  return (
    <nav className="flex w-[196px] shrink-0 flex-col bg-sidebar px-4 pt-3 pb-4">
      <div data-tauri-drag-region className="h-8 shrink-0" />
      <div data-tauri-drag-region className="flex items-center gap-2.5 pt-[25px] pb-8">
        <img src="/icon.png" alt="" className="pointer-events-none size-[34px]" />
        <div className="pointer-events-none flex flex-col gap-1">
          <span className="font-semibold text-[13px]">招行理财值守</span>
          <span className="text-[11px] text-muted">本机管理</span>
        </div>
      </div>
      <ul className="flex flex-col gap-[7px]">
        {PAGES.map(({ path, title, icon: Icon }) => {
          const selected = current === path
          return (
            <li key={path}>
              <Link
                to={path}
                className={cn(
                  'relative flex items-center gap-[11px] rounded-[9px] px-3 py-3 text-[13px]',
                  selected ? 'font-semibold text-white' : 'text-muted hover:text-fg',
                )}
              >
                {selected && <span className="absolute inset-0 rounded-[9px] bg-button" />}
                <Icon className="relative size-[15px]" />
                <span className="relative">{title}</span>
                {active && path === '/tasks' && (
                  <span className="relative ml-auto flex size-[7px]" title="值守中">
                    <span className="absolute inset-0 animate-ping rounded-full bg-accent opacity-60" />
                    <span className="relative size-[7px] rounded-full bg-accent" />
                  </span>
                )}
              </Link>
            </li>
          )
        })}
      </ul>
      <div className="mt-auto pt-4">
        <AnimatePresence>{showBubble && <WatchBubble key="bubble" />}</AnimatePresence>
      </div>
    </nav>
  )
}

function Header({ title, subtitle, path }: { title: string; subtitle: string; path: string }) {
  const busy = useUI((s) => s.busy)
  const busyLabel = useUI((s) => s.busyLabel)
  const lastRefresh = useUI((s) => s.lastRefresh)
  const refresh = useRefreshPage()
  return (
    <header
      data-tauri-drag-region
      className="flex h-[54px] shrink-0 items-center px-[26px] pt-5 [box-sizing:content-box]"
    >
      <div className="pointer-events-none flex flex-1 flex-col gap-1.5">
        <h1 className="font-semibold text-[23px]">{title}</h1>
        <span className="text-muted text-xs">
          {lastRefresh ? `${subtitle} · 上次刷新 ${clockTime(lastRefresh)}` : subtitle}
        </span>
      </div>
      <AnimatePresence>
        {busy && (
          <motion.div
            initial={{ opacity: 0, x: 8 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0 }}
            className="mr-3 flex items-center gap-[7px]"
          >
            <Spinner />
            <span className="text-[11px] text-muted">{busyLabel}</span>
          </motion.div>
        )}
      </AnimatePresence>
      <Button disabled={busy} onClick={() => refresh(path)}>
        <RotateCw className="size-3.5" />
        刷新
      </Button>
    </header>
  )
}

const rootRoute = createRootRoute({ component: Layout })
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  beforeLoad: () => {
    throw redirect({ to: lastPage() })
  },
})
const pageRoutes = PAGES.map(({ path, component }) =>
  createRoute({ getParentRoute: () => rootRoute, path, component }),
)

export const router = createRouter({
  routeTree: rootRoute.addChildren([indexRoute, ...pageRoutes]),
  history: createHashHistory(),
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
