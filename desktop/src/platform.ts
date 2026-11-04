import { invoke } from '@tauri-apps/api/core'
import { isTauri } from './api/client'

const TITLE = '招行理财值守'

export async function notify(body: string) {
  if (isTauri) {
    const { isPermissionGranted, requestPermission, sendNotification } = await import(
      '@tauri-apps/plugin-notification'
    )
    if ((await isPermissionGranted()) || (await requestPermission()) === 'granted') {
      sendNotification({ title: TITLE, body })
    }
  } else if ('Notification' in window && Notification.permission === 'granted') {
    new Notification(TITLE, { body })
  }
}

export interface BackendConfig {
  root: string
  python: string
}

/** Project folder and Python used to start the backend; only the shell can change them. */
export function backendConfig() {
  return invoke<BackendConfig>('backend_config')
}

export function setBackendConfig(config: BackendConfig) {
  return invoke<BackendConfig>('set_backend_config', { config })
}
