import type { components } from './schema'

// Request bodies come from the server's OpenAPI schema (`pnpm api:types`).
export type ArmRequest = components['schemas']['ArmRequest']
export type BuyRequest = components['schemas']['BuyRequest']
export type CancelRequest = components['schemas']['CancelRequest']

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
}

export interface Status {
  task: Task | null
  running: boolean
  last_tick_age_s?: number | null
  logs?: string[]
  agent: { state: 'none' | 'watching' | 'stale'; session?: string; last_seen?: string }
  credentials: { state?: string }
  mail_configured: boolean
  log_path: string
  favorites: Favorite[]
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

export interface Info {
  root: string
  python: string
  log_path: string
  skill_path: string
}

export interface CommandResult {
  output?: string[]
}
