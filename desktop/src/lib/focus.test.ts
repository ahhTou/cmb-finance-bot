import { describe, expect, it } from 'vitest'
import { type FocusDocument, type FocusWindow, isWindowActive, watchWindowActive } from './focus'

type Listener = () => void

/** A DOM-free event target: enough for the focus/visibility listeners under test. */
function eventTarget() {
  const listeners = new Map<string, Set<Listener>>()
  return {
    addEventListener(type: string, listener: Listener) {
      const set = listeners.get(type) ?? new Set<Listener>()
      set.add(listener)
      listeners.set(type, set)
    },
    removeEventListener(type: string, listener: Listener) {
      listeners.get(type)?.delete(listener)
    },
    emit(type: string) {
      for (const listener of [...(listeners.get(type) ?? [])]) listener()
    },
    count(type: string) {
      return listeners.get(type)?.size ?? 0
    },
  }
}

/** A window/document pair sharing one fake event target, as in a real page. */
function focusTarget(hasFocus = true) {
  const events = eventTarget()
  const doc: FocusDocument = {
    hidden: false,
    hasFocus: () => hasFocus,
    addEventListener: events.addEventListener,
    removeEventListener: events.removeEventListener,
  }
  const win: FocusWindow = {
    document: doc,
    addEventListener: events.addEventListener,
    removeEventListener: events.removeEventListener,
  }
  return { win, doc, emit: events.emit, count: events.count }
}

describe('isWindowActive', () => {
  it('is active only when the document is focused and visible', () => {
    const cases = [
      [true, false, true],
      [false, false, false],
      [true, true, false],
      [false, true, false],
    ] as const
    for (const [hasFocus, hidden, expected] of cases) {
      const { win, doc } = focusTarget(hasFocus)
      doc.hidden = hidden
      expect(isWindowActive(win, doc), `hasFocus=${hasFocus} hidden=${hidden}`).toBe(expected)
    }
  })

  it('treats another document as inactive', () => {
    const { win } = focusTarget()
    const { doc } = focusTarget()
    expect(isWindowActive(win, doc)).toBe(false)
  })
})

describe('watchWindowActive', () => {
  it('reports blur, focus and visibility changes', () => {
    const { win, doc, emit } = focusTarget()
    const seen: boolean[] = []
    watchWindowActive(win, doc, (active) => seen.push(active))

    emit('blur')
    expect(seen).toEqual([false])

    emit('focus')
    expect(seen).toEqual([false, true])

    doc.hidden = true
    emit('visibilitychange')
    expect(seen).toEqual([false, true, false])

    doc.hidden = false
    emit('visibilitychange')
    expect(seen).toEqual([false, true, false, true])
  })

  it('ignores visibility changes that keep the document hidden', () => {
    const { win, doc, emit } = focusTarget(false)
    doc.hidden = true
    const seen: boolean[] = []
    watchWindowActive(win, doc, (active) => seen.push(active))

    emit('visibilitychange')
    expect(seen).toEqual([false])
  })

  it('removes every listener when unsubscribed', () => {
    const { win, doc, emit, count } = focusTarget()
    const seen: boolean[] = []
    const stop = watchWindowActive(win, doc, (active) => seen.push(active))
    expect(count('focus')).toBe(1)
    expect(count('blur')).toBe(1)
    expect(count('visibilitychange')).toBe(1)

    stop()
    expect(count('focus')).toBe(0)
    expect(count('blur')).toBe(0)
    expect(count('visibilitychange')).toBe(0)

    emit('blur')
    emit('focus')
    expect(seen).toEqual([])
  })
})
