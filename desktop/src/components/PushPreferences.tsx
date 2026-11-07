import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { q, useAction } from '../api/hooks'
import type { PushPreferences, PushPreferencesView } from '../api/types'
import { useUI } from '../store'
import { Button } from './ui/button'
import { Card, Hint } from './ui/card'
import { Switch } from './ui/form'

export function PushPreferencesCard() {
  const { data, error } = useQuery({ ...q.pushPreferences, staleTime: 0 })
  const qc = useQueryClient()
  const action = useAction()
  const busy = useUI((s) => s.busy)
  const [draft, setDraft] = useState<PushPreferences | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (data && draft === null) setDraft({ enabled: data.enabled, events: { ...data.events } })
  }, [data, draft])

  const dirty = !!(
    data &&
    draft &&
    (draft.enabled !== data.enabled ||
      data.catalog.some((event) => draft.events[event.key] !== data.events[event.key]))
  )
  const groups = [...new Set(data?.catalog.map((event) => event.group) ?? [])]

  function change(patch: Partial<PushPreferences>) {
    setDraft((current) => (current ? { ...current, ...patch } : current))
    setSaved(false)
  }

  async function save() {
    if (!draft) return
    const result = await action(
      '保存通知选项',
      () => api<PushPreferencesView>('PUT', '/api/push/preferences', draft),
      false,
    )
    if (!result) return
    qc.setQueryData(q.pushPreferences.queryKey, result)
    setDraft({ enabled: result.enabled, events: { ...result.events } })
    setSaved(true)
  }

  return (
    <Card title="通知场景" subtitle="按情况选择手机推送；关闭通知后仍会记录日志。">
      <div data-testid="push-preferences" className="flex flex-col gap-4">
        {error && <Hint tone="warn">通知选项读取失败：{error.message}</Hint>}
        {!data || !draft ? (
          <Hint>正在读取通知选项…</Hint>
        ) : (
          <>
            <div className="rounded-xl bg-field px-4 py-3">
              <Switch
                label="开启手机推送"
                checked={draft.enabled}
                disabled={busy}
                onChange={(enabled) => change({ enabled })}
              />
              <p className="mt-2 text-[11px] text-muted">
                {draft.enabled
                  ? '下列已勾选的场景会发送通知。'
                  : '手机推送已关闭；下列选择会保留，测试推送仍可发送。'}
                保存后对后续通知立即生效，不影响计划和购买配置。
              </p>
            </div>
            <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
              {groups.map((group) => (
                <section key={group} className="rounded-xl bg-field/60 p-3.5">
                  <h3 className="mb-2 font-semibold text-xs">{group}</h3>
                  <div className="flex flex-col divide-y divide-white/5">
                    {data.catalog
                      .filter((event) => event.group === group)
                      .map((event) => (
                        <div
                          key={event.key}
                          data-testid={`push-option-${event.key}`}
                          className="py-3 first:pt-1 last:pb-1"
                        >
                          <Switch
                            label={event.label}
                            checked={draft.events[event.key] ?? true}
                            disabled={busy || !draft.enabled}
                            onChange={(enabled) =>
                              change({ events: { ...draft.events, [event.key]: enabled } })
                            }
                          />
                          <p className="mt-1.5 pr-12 text-[11px] leading-relaxed text-muted">
                            {event.description}
                          </p>
                        </div>
                      ))}
                  </div>
                </section>
              ))}
            </div>
            <div className="sticky bottom-0 flex flex-wrap items-center gap-3 rounded-xl bg-card px-3 py-3 shadow-lg">
              <Hint className="flex-1">
                {dirty
                  ? '通知选项有未保存的修改。'
                  : saved
                    ? '通知选项已保存。'
                    : '测试推送不受总开关和场景开关限制。'}
              </Hint>
              <Button
                disabled={busy || !dirty}
                onClick={() => {
                  setDraft({ enabled: data.enabled, events: { ...data.events } })
                  setSaved(false)
                }}
              >
                撤销修改
              </Button>
              <Button
                data-testid="push-preferences-save"
                variant="primary"
                disabled={busy || !dirty}
                onClick={save}
              >
                保存通知选项
              </Button>
            </div>
          </>
        )}
      </div>
    </Card>
  )
}
