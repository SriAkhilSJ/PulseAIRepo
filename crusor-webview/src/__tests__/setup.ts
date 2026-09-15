// jsdom polyfills for the browser APIs CopilotKit v2 touches on mount.
// Without these the provider throws before any DOM is produced, which would
// make a render test silently pass-by-absence instead of failing loudly.

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

class IntersectionObserverStub {
  readonly root = null
  readonly rootMargin = ''
  readonly thresholds: number[] = []
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return []
  }
}

class MutationObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return []
  }
}

const g = globalThis as unknown as Record<string, unknown>

g.ResizeObserver ??= ResizeObserverStub
g.IntersectionObserver ??= IntersectionObserverStub
g.MutationObserver ??= MutationObserverStub

if (typeof window !== 'undefined') {
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia

  Element.prototype.scrollIntoView ??= function scrollIntoView() {}
  Element.prototype.scrollTo ??= function scrollTo() {}
  Element.prototype.animate ??= (function animate() {
    return { cancel() {}, finish() {}, addEventListener() {}, removeEventListener() {} }
  }) as unknown as typeof Element.prototype.animate

  if (!('DOMRect' in window)) {
    // @ts-expect-error - minimal DOMRect for layout-dependent components
    window.DOMRect = class DOMRect {
      constructor(
        public x = 0,
        public y = 0,
        public width = 0,
        public height = 0,
      ) {}
      get top() {
        return this.y
      }
      get left() {
        return this.x
      }
      get right() {
        return this.x + this.width
      }
      get bottom() {
        return this.y + this.height
      }
      static fromRect(r?: DOMRectInit) {
        return new DOMRect(r?.x, r?.y, r?.width, r?.height)
      }
      toJSON() {
        return { ...this }
      }
    }
  }
}
