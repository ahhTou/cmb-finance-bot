import { useEffect, useState } from 'react'

/** The part of `document` the focus check and its listeners need. */
export interface FocusDocument {
  hidden: boolean
  hasFocus(): boolean
  addEventListener(type: 'visibilitychange', listener: () => void): void
  removeEventListener(type: 'visibilitychange', listener: () => void): void
}

/** The part of `window` the focus check and its listeners need. */
export interface FocusWindow {
  document: FocusDocument
  addEventListener(type: 'focus' | 'blur', listener: () => void): void
  removeEventListener(type: 'focus' | 'blur', listener: () => void): void
}

/**
 * Whether this window is both focused and visible. The focus view uses it to
 * stop every decorative animation while the window is in the background; data
 * polling and the event stream are not affected.
 */
export function isWindowActive(win: FocusWindow, doc: FocusDocument) {
  // Only the window's own document can report that window's focus.
  return win.document === doc && doc.hasFocus() && !doc.hidden
}

/**
 * Subscribes to the window focus/blur and document visibility events that can
 * change {@link isWindowActive} and reports every resulting value.
 * Returns the unsubscribe function.
 *
 * `focus`/`blur` set the state directly instead of re-reading `hasFocus()`:
 * a real window already reports the new state by the time the handler runs,
 * while a synthetic event (tests) only tells us that it changed.
 */
export function watchWindowActive(
  win: FocusWindow,
  doc: FocusDocument,
  onChange: (active: boolean) => void,
): () => void {
  const onFocus = () => onChange(!doc.hidden)
  const onBlur = () => onChange(false)
  const onVisibility = () => onChange(isWindowActive(win, doc))
  win.addEventListener('focus', onFocus)
  win.addEventListener('blur', onBlur)
  doc.addEventListener('visibilitychange', onVisibility)
  return () => {
    win.removeEventListener('focus', onFocus)
    win.removeEventListener('blur', onBlur)
    doc.removeEventListener('visibilitychange', onVisibility)
  }
}

/**
 * `true` while this window is focused and visible; `false` while it sits in the
 * background. Initialised on first render and kept current by focus/blur and
 * visibilitychange for the lifetime of the component.
 */
export function useWindowActive(): boolean {
  const [active, setActive] = useState(() =>
    typeof window === 'undefined' ? true : isWindowActive(window, document),
  )
  useEffect(() => watchWindowActive(window, document, setActive), [])
  return active
}
