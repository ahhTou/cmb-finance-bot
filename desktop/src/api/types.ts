import type { components } from './schema'

// Request bodies come from the server's OpenAPI schema (`pnpm api:types`).
export type ArmRequest = components['schemas']['ArmRequest']
export type BuyRequest = components['schemas']['BuyRequest']
export type CancelRequest = components['schemas']['CancelRequest']
export type PlanItemRequest = components['schemas']['PlanItemRequest']
export type PlanRequest = components['schemas']['PlanRequest']
// Kept explicit until the shared OpenAPI generation catches up with this contract.
export interface PlanStartRequest {
  plan_id: string
  content_revision: string
  settings_revision: string
  confirm_real_payment: boolean
}
export type PushRequest = components['schemas']['PushRequest']

// Responses are whatever admin_cli.py prints; these describe the fields the app reads.
export type Mode = 'first_launch' | 'redemption'

export interface Task {
  code?: string
  amount?: string
  at?: string
  fire_at?: string
  end_at?: string
  armed_at?: string
  mode?: Mode
  phase?: string
  dry_run?: boolean
  prep_minutes?: number
  window_minutes?: number | null
  patterns_sent?: number
  pid?: number
}

export interface Favorite {
  code: string
  title?: string
  /** Set on the one test item; drills use this product and amount by default. */
  test_amount?: string | null
}

/** The saved product + amount drills fill in, from the favourites page. */
export interface TestItem {
  code: string
  amount: string
  title?: string
}

export interface Status {
  task: Task | null
  running: boolean
  last_tick_age_s?: number | null
  logs?: string[]
  agent: { state: 'none' | 'watching' | 'stale'; session?: string; last_seen?: string }
  credentials: { state?: string }
  push_configured: boolean
  log_path: string
  favorites: Favorite[]
  /** The test item, if one is set. */
  test_item?: TestItem | null
}

export interface Device {
  emulator?: { running?: boolean }
  booted?: boolean
  app_pid?: string
  resolution?: string
  resolution_ok?: boolean
  awake?: boolean
  ac_powered?: boolean
  stay_on?: string
  screen_timeout?: string
  lock_disabled?: string
}

export interface SystemInfo {
  on_ac?: boolean
  clamshell?: string
  watch_caffeinate?: boolean
  network_ok?: boolean
  network_s?: number | null
  sleep_settings?: string
}

export interface HistoryRecord extends Task {
  ended_at?: string
  fired_at?: string
  result?: string | null
  resumes?: { at?: string; by?: string; reason?: string }[]
}

export interface History {
  records: HistoryRecord[]
  total: number
  shown: number
  log_path: string
}

export interface Log {
  path: string
  lines: string[]
  total: number
  exists: boolean
}

export interface PurchaseSettings {
  settings: Record<string, number>
  settings_revision: string
}

/** GET/PUT/DELETE /api/push; never includes the token itself. */
export interface PushConfig {
  configured: boolean
  server: string | null
  topic: string | null
  token_set: boolean
}

export interface PushPreferences {
  enabled: boolean
  events: Record<string, boolean>
}

export interface PushPreferencesView extends PushPreferences {
  catalog: { key: string; label: string; description: string; group: string }[]
}

/** POST /api/push/test: delivered, or why the server refused it. */
export interface PushTestResult {
  sent: boolean
  error?: string
}

export interface Info {
  root: string
  python: string
  log_path: string
  skill_path: string
}

export interface CommandResult {
  output?: string[]
}

// Plan mode responses come from watch_plan.view() via admin_cli.py `plan`.
// Handwritten per var/team/plan-mode-contract.md §4.5; `schema.d.ts` is
// regenerated separately and only covers request bodies.

export type PlanPhase = 'idle' | 'running' | 'done' | 'aborted' | 'disarmed'
export type PlanItemState = 'pending' | 'running' | 'done' | 'failed' | 'skipped'

export interface PlanItem {
  item_id?: string
  code: string
  amount: string
  /** Purchase time, naive local ISO seconds ("2026-11-07T09:00:00"). */
  at: string
  mode: Mode
  state?: PlanItemState
  outcome?: 'success' | 'failed' | 'dry_run' | 'unknown' | null
  task_id?: string | null
  result?: string | null
  armed_at?: string | null
  ended_at?: string | null
  /** Computed by the backend view; absent on the request/save payload. */
  prep_at?: string
  end_at?: string
}

export interface Plan {
  version?: number
  plan_id?: string
  content_revision?: string
  generation?: string | null
  created_at?: string | null
  started_at?: string | null
  ended_at?: string | null
  dry_run: boolean
  phase?: PlanPhase
  pid?: number | null
  last_tick?: string | null
  settings_revision?: string | null
  result?: string | null
  items: PlanItem[]
}

export interface PlanView {
  plan: Plan | null
  running: boolean
  stale: boolean
  problems: string[]
  warnings: string[]
  task: Task | null
  log_path?: string
  logs?: string[]
  settings_revision?: string
  now?: string
}
