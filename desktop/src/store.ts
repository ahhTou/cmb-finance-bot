import { create } from 'zustand'

/** Client-only state. Everything the backend owns lives in the TanStack Query cache. */
interface UIState {
  busy: boolean
  busyLabel: string
  message: string | null
  commandOutput: string[]
  screenshotUrl: string | null
  lastRefresh: Date | null
  /** Open modal dialogs; while any is open the window-level toast is hidden. */
  dialogs: number
  start: (label: string) => void
  finish: () => void
  setMessage: (message: string | null) => void
  /** For background reads: skipped while another message shows or the user dismissed this one. */
  report: (message: string) => void
  dismissed: string | null
  setOutput: (lines: string[]) => void
  setScreenshot: (url: string | null) => void
  touch: () => void
  dialogOpened: () => () => void
}

export const useUI = create<UIState>((set, get) => ({
  busy: false,
  busyLabel: '',
  message: null,
  commandOutput: [],
  screenshotUrl: null,
  lastRefresh: null,
  dialogs: 0,
  start: (label) => set({ busy: true, busyLabel: label, message: null }),
  finish: () => set({ busy: false, busyLabel: '' }),
  setMessage: (message) => set((s) => ({ message, dismissed: message === null ? s.message : s.dismissed })),
  report: (message) => {
    const { message: shown, dismissed } = get()
    if (!shown && message !== dismissed) set({ message })
  },
  dismissed: null,
  setOutput: (commandOutput) => set({ commandOutput }),
  setScreenshot: (url) => {
    const previous = get().screenshotUrl
    if (previous) URL.revokeObjectURL(previous)
    set({ screenshotUrl: url })
  },
  touch: () => set({ lastRefresh: new Date() }),
  dialogOpened: () => {
    set((s) => ({ dialogs: s.dialogs + 1 }))
    return () => set((s) => ({ dialogs: s.dialogs - 1 }))
  },
}))
