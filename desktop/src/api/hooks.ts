import { queryOptions, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef } from 'react'
import { ACTIVE_PHASES, clockTime, phaseName } from '../lib/utils'
import { notify } from '../platform'
import { useUI } from '../store'
import { api, subscribe } from './client'
import type {
  Device,
  History,
  Info,
  Log,
  PlanSettings,
  PlanView,
  PurchaseSettings,
  PushConfig,
  PushPreferencesView,
  Status,
  SystemInfo,
} from './types'

export const q = {
  status: queryOptions({
    queryKey: ['status'],
    queryFn: () => api<Status>('GET', '/api/status'),
    staleTime: Number.POSITIVE_INFINITY, // kept fresh by the event stream
  }),
  device: queryOptions({ queryKey: ['device'], queryFn: () => api<Device>('GET', '/api/device') }),
  system: queryOptions({ queryKey: ['system'], queryFn: () => api<SystemInfo>('GET', '/api/system') }),
  history: queryOptions({ queryKey: ['history'], queryFn: () => api<History>('GET', '/api/history') }),
  log: (lines: number) =>
    queryOptions({ queryKey: ['log', lines], queryFn: () => api<Log>('GET', `/api/log?lines=${lines}`) }),
  settings: queryOptions({
    queryKey: ['settings'],
    queryFn: () => api<PurchaseSettings>('GET', '/api/settings'),
  }),
  planSettings: queryOptions({
    queryKey: ['plan-settings'],
    queryFn: () => api<PlanSettings>('GET', '/api/settings/other'),
  }),
  push: queryOptions({
    queryKey: ['push'],
    queryFn: () => api<PushConfig>('GET', '/api/push'),
  }),
  pushPreferences: queryOptions({
    queryKey: ['push-preferences'],
    queryFn: () => api<PushPreferencesView>('GET', '/api/push/preferences'),
  }),
  info: queryOptions({ queryKey: ['info'], queryFn: () => api<Info>('GET', '/api/info') }),
  // Plan mode: poll every 2 s only while the plan process is running, so item
  // states, last_tick and logs follow along. When it is not running one read is enough.
  plan: queryOptions({
    queryKey: ['plan'],
    queryFn: () => api<PlanView>('GET', '/api/plan'),
    refetchInterval: (query) => (query.state.data?.running ? 2000 : false),
  }),
}

/** The current watch task and what it allows, derived from the status query. */
export function useWatch() {
  const { data: status } = useQuery(q.status)
  const task = status?.task ?? null
  const phase = task?.phase ?? '未布防'
  const credentials = status?.credentials?.state
  return {
    status,
    task,
    phase,
    active: ACTIVE_PHASES.includes(phase),
    running: status?.running === true,
    credentialsDisabled: ['preparing', 'waiting', 'firing'].includes(phase),
    credentialState:
      credentials === 'configured'
        ? '已设置'
        : credentials === 'invalid'
          ? '格式无效'
          : credentials === 'unavailable'
            ? '未设置或无法读取'
            : '未知',
    pushConfigured: status?.push_configured === true,
    agentShort:
      status?.agent?.state === 'watching' ? '监听中' : status?.agent?.state === 'stale' ? '已失联' : '未监听',
    favorites: status?.favorites ?? [],
    testItem: status?.test_item ?? null,
  }
}

/**
 * Runs one backend action at a time, like the native app: shows the busy label,
 * turns failures into the toast, and refreshes status afterwards.
 * Resolves to the result, or null when it failed or another action was running.
 */
export function useAction() {
  const qc = useQueryClient()
  return useCallback(
    async <T>(label: string, run: () => Promise<T>, refreshAfter = true): Promise<T | null> => {
      const ui = useUI.getState()
      if (ui.busy) return null
      ui.start(label)
      try {
        const result = await run()
        if (refreshAfter) await qc.invalidateQueries({ queryKey: q.status.queryKey })
        return result
      } catch (error) {
        useUI.getState().setMessage(error instanceof Error ? error.message : String(error))
        return null
      } finally {
        useUI.getState().finish()
      }
    },
    [qc],
  )
}

/** What the header's 刷新 reloads on each page. */
export function useRefreshPage() {
  const qc = useQueryClient()
  const action = useAction()
  return useCallback(
    (path: string) => {
      const fresh = { staleTime: 0 }
      const status = () => qc.fetchQuery({ ...q.status, ...fresh })
      const device = () => qc.fetchQuery({ ...q.device, ...fresh })
      const sets: Record<string, (() => Promise<unknown>)[]> = {
        '/status': [status, device, () => qc.fetchQuery({ ...q.system, ...fresh })],
        '/plan': [() => qc.fetchQuery({ ...q.plan, ...fresh }), status],
        '/drill': [status, device],
        '/settings': [
          status,
          () => qc.fetchQuery({ ...q.push, ...fresh }),
          () => qc.fetchQuery({ ...q.pushPreferences, ...fresh }),
          () => qc.fetchQuery({ ...q.planSettings, ...fresh }),
        ],
        '/history': [
          () => qc.fetchQuery({ ...q.history, ...fresh }),
          () => qc.fetchQuery({ ...q.log(800), ...fresh }),
        ],
      }
      const list = sets[path] ?? [status]
      return action(
        '刷新状态',
        async () => {
          await Promise.all(list.map((load) => load()))
          useUI.getState().touch()
        },
        false,
      )
    },
    [qc, action],
  )
}

/**
 * Keeps status fresh from the server's event stream while the window is visible,
 * and posts a system notification when an active task changes phase.
 */
export function useStatusEvents() {
  const qc = useQueryClient()
  const previous = useRef<string | null>(null)
  useEffect(() => {
    let stop: (() => void) | null = null
    const onStatus = (data: unknown) => {
      const status = data as Status
      const phase = status.task?.phase ?? '未布防'
      if (previous.current && previous.current !== phase && previous.current !== '未布防') {
        notify(`阶段：${phaseName(phase)} · ${clockTime(new Date())}`)
      }
      previous.current = phase
      qc.setQueryData(q.status.queryKey, status)
      useUI.getState().touch()
    }
    const onFailure = (data: unknown) => {
      useUI.getState().report((data as { error: string }).error)
    }
    const start = () => {
      stop ??= subscribe({ status: onStatus, failure: onFailure })
    }
    const pause = () => {
      stop?.()
      stop = null
    }
    const onVisibility = () => (document.hidden ? pause() : start())
    if (!document.hidden) start()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      pause()
    }
  }, [qc])
}
