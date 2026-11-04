import { invoke } from '@tauri-apps/api/core'

export class ApiError extends Error {}

interface Backend {
  url: string
  token: string | null
}

export const isTauri = '__TAURI_INTERNALS__' in window

let backend: Promise<Backend> | null = null

/**
 * In the Tauri shell the backend runs on a random port with a random token, both
 * handed out by the Rust side. In the browser the Vite proxy (or MSW) answers `/api`.
 */
function resolveBackend() {
  if (!backend) {
    backend = isTauri ? invoke<Backend>('backend') : Promise.resolve({ url: '', token: null })
    backend.catch(() => {
      backend = null
    })
  }
  return backend
}

/** Drop the cached address after the shell restarted the backend. */
export function resetBackend() {
  backend = null
}

async function send(method: string, path: string, body?: unknown, signal?: AbortSignal) {
  let target: Backend
  try {
    target = await resolveBackend()
  } catch (error) {
    throw new ApiError(String(error))
  }
  const headers: Record<string, string> = {}
  if (target.token) headers.Authorization = `Bearer ${target.token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  try {
    return await fetch(target.url + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new ApiError('无法连接本地后端，请检查设置中的项目目录和 Python 路径。')
  }
}

export async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await send(method, path, body)
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(data?.error ?? `请求失败（${res.status}）。`)
  return data as T
}

/** Fetches an authenticated image and returns an object URL for <img src>. */
export async function blobUrl(path: string) {
  const res = await send('GET', path)
  if (!res.ok) throw new ApiError('截图读取失败。')
  return URL.createObjectURL(await res.blob())
}

/**
 * Reads the server-sent event stream with fetch (EventSource cannot send the token)
 * and reconnects after a pause when it drops. Returns an unsubscribe function.
 */
export function subscribe(handlers: Record<string, (data: unknown) => void>) {
  const controller = new AbortController()
  const decoder = new TextDecoder()
  async function loop() {
    while (!controller.signal.aborted) {
      try {
        const res = await send('GET', '/api/events', undefined, controller.signal)
        if (!res.ok || !res.body) throw new ApiError(`事件流不可用（${res.status}）。`)
        const reader = res.body.getReader()
        let buffer = ''
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          let end = buffer.indexOf('\n\n')
          while (end >= 0) {
            dispatch(buffer.slice(0, end))
            buffer = buffer.slice(end + 2)
            end = buffer.indexOf('\n\n')
          }
        }
      } catch (error) {
        if (controller.signal.aborted) return
        handlers.failure?.({ error: error instanceof Error ? error.message : String(error) })
      }
      await new Promise((resolve) => setTimeout(resolve, 3000))
    }
  }
  function dispatch(chunk: string) {
    let event = 'message'
    let data = ''
    for (const line of chunk.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data += line.slice(5).trim()
    }
    try {
      handlers[event]?.(JSON.parse(data))
    } catch {
      // Ignore a malformed event; the next one replaces it.
    }
  }
  loop()
  return () => controller.abort()
}
