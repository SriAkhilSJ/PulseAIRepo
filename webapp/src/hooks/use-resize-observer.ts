import { type RefObject, useLayoutEffect, useRef } from 'react'

// Port: hermes apps/desktop/src/hooks/use-resize-observer.ts — the shared
// single-observer design and its rationale are hers, verbatim where read;
// the WeakMap routing below is her structure.
type Handler = (entries: readonly ResizeObserverEntry[]) => void

const handlers = new WeakMap<Element, Set<Handler>>()

let shared: null | ResizeObserver = null

function sharedObserver(): null | ResizeObserver {
  if (typeof ResizeObserver === 'undefined') {
    return null
  }

  if (!shared) {
    shared = new ResizeObserver(entries => {
      // Group this delivery's entries by handler so a caller observing several
      // elements is still invoked once, with all of its entries.
      const byHandler = new Map<Handler, ResizeObserverEntry[]>()

      for (const entry of entries) {
        const targets = handlers.get(entry.target)

        if (!targets) {
          continue
        }

        for (const handler of targets) {
          const list = byHandler.get(handler)

          if (list) {
            list.push(entry)
          } else {
            byHandler.set(handler, [entry])
          }
        }
      }

      for (const [handler, group] of byHandler) {
        handler(group)
      }
    })
  }

  return shared
}

export function useResizeObserver(
  onResize: (entries: readonly ResizeObserverEntry[]) => void,
  ...refs: readonly RefObject<Element | null>[]
) {
  const refsRef = useRef(refs)
  refsRef.current = refs

  const handlerRef = useRef(onResize)
  handlerRef.current = onResize

  useLayoutEffect(() => {
    const observer = sharedObserver()

    if (!observer) {
      handlerRef.current([])

      return
    }

    const observed: Element[] = []

    for (const ref of refsRef.current) {
      const element = ref.current

      if (!element) {
        continue
      }

      let existing = handlers.get(element)

      if (!existing) {
        existing = new Set()
        handlers.set(element, existing)
        observer.observe(element)
      }

      // Stable wrapper; handlerRef.current is refreshed every render, so the
      // caller's latest callback is what fires without re-observing.
      const stable = (entries: readonly ResizeObserverEntry[]) => handlerRef.current(entries)
      existing.add(stable)

      observed.push(element)
    }

    return () => {
      for (const element of observed) {
        const set = handlers.get(element)

        if (!set) {
          continue
        }

        set.clear()
        handlers.delete(element)
        observer.unobserve(element)
      }
    }
  }, [])
}
