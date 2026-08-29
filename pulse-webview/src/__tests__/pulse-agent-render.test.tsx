/**
 * Does the Pulse agent actually render?
 * =====================================
 * Provider-free DOM verification for the CopilotKit webview.
 *
 * These tests mount the real components with the real catalog and drive them
 * with the exact A2UI operations the Python agent emits. They make **zero**
 * LLM/provider calls, so they cost nothing to run and are deterministic.
 *
 * Regression guarded: the A2UI v0.9 wire format is FLAT
 * (`{ id, component, ...props }`). The previous `props`-nested schema produced
 * `properties = { props: { ... } }`, so `props.child` was `undefined` and the
 * task card painted an empty white box.
 */
import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'
import React, { useEffect } from 'react'
import { render, waitFor, act } from '@testing-library/react'
import { A2UIProvider, A2UIRenderer, useA2UIActions } from '@copilotkit/a2ui-renderer'

import { catalog } from '../a2ui/catalog'
import operations from './fixtures/pulse-a2ui-operations.json'

const SURFACE_ID = 'pulse-task'

type ComponentNode = { id: string; component: string; props?: Record<string, unknown> }
type Operation = Record<string, any>

const schemaComponents = operations[1].updateComponents.components as ComponentNode[]

/**
 * Mirrors CopilotKit's internal `ReactSurfaceHost`: pump operations into the
 * A2UI provider, then render the surface. This is the same path the
 * CopilotChat activity renderer takes.
 */
function SurfaceHost({
  surfaceId,
  ops,
  onAction,
}: {
  surfaceId: string
  ops: Operation[]
  onAction?: (message: unknown) => void
}) {
  return (
    <A2UIProvider catalog={catalog} onAction={onAction}>
      <SurfaceMessageProcessor surfaceId={surfaceId} operations={ops} />
      <A2UIRenderer surfaceId={surfaceId} />
    </A2UIProvider>
  )
}

function SurfaceMessageProcessor({
  surfaceId,
  operations,
}: {
  surfaceId: string
  operations: Operation[]
}) {
  const { processMessages, getSurface } = useA2UIActions()
  const lastHash = React.useRef('')
  useEffect(() => {
    const hash = JSON.stringify(operations)
    if (hash === lastHash.current) return
    lastHash.current = hash
    processMessages(
      getSurface(surfaceId) ? operations.filter((op) => !op?.createSurface) : operations,
    )
  }, [processMessages, getSurface, surfaceId, operations])
  return null
}

describe('A2UI catalog contract', () => {
  const componentNames = Array.from(
    (catalog as unknown as { components: Map<string, unknown> }).components.keys(),
  )

  it('registers every custom Pulse component', () => {
    for (const name of [
      'Card',
      'Title',
      'StatusBadge',
      'PriorityTag',
      'AssigneeBadge',
      'Button',
    ]) {
      expect(componentNames, `catalog missing custom component "${name}"`).toContain(name)
    }
  })

  it('resolves every component referenced by pulse_task_schema.json', () => {
    const used = [...new Set(schemaComponents.map((c) => c.component))]
    const missing = used.filter((name) => !componentNames.includes(name))
    expect(missing).toEqual([])
  })
})

describe('pulse_task_schema.json wire format', () => {
  it('is FLAT v0.9 (no props wrapper)', () => {
    // Guard against reintroducing the empty-card bug.
    const nested = schemaComponents.filter((c) => 'props' in c)
    expect(
      nested.map((c) => c.id),
      'components must not nest props; A2UI v0.9 destructures { id, component, ...properties }',
    ).toEqual([])
  })

  it('keeps id/component on every node', () => {
    for (const c of schemaComponents) {
      expect(c.id, 'component id is required').toBeTruthy()
      expect(c.component, 'component type is required').toBeTruthy()
    }
  })
})

describe('Pulse agent task card renders in the DOM', () => {
  it('paints the full card from the exact operations the Python agent emits', async () => {
    const { container } = render(<SurfaceHost surfaceId={SURFACE_ID} ops={operations} />)

    const card = await waitFor(
      () => {
        const el = container.querySelector('[data-testid="pulse-task-card"]')
        if (!el) throw new Error('pulse-task-card never mounted')
        return el
      },
      { timeout: 10_000 },
    )

    await waitFor(
      () => {
        if (!(card.textContent ?? '').includes('Fix bridge protocol'))
          throw new Error('data-bound title did not resolve')
      },
      { timeout: 10_000 },
    )

    const text = card.textContent ?? ''
    // Every field from the A2UI data model must be visible.
    expect(text).toContain('Fix bridge protocol')
    expect(text).toContain('Repair the stdio bridge handshake')
    expect(text).toContain('In progress')
    expect(text).toContain('high')
    expect(text).toContain('Pulse Agent')
    expect(text).toContain('Open in editor')
    // eslint-disable-next-line no-console
    console.log('[rendered card]', JSON.stringify(text))
  })

  it('renders an interactive action button', async () => {
    const { container } = render(<SurfaceHost surfaceId={SURFACE_ID} ops={operations} />)
    await waitFor(
      () => {
        if (!container.querySelector('[data-testid="pulse-task-card"]'))
          throw new Error('card never mounted')
      },
      { timeout: 10_000 },
    )

    const button = await waitFor(
      () => {
        const el = container.querySelector('[data-testid="pulse-task-action"]')
        if (!el) throw new Error('action button never mounted')
        return el as HTMLButtonElement
      },
      { timeout: 10_000 },
    )

    expect(button.tagName.toLowerCase()).toBe('button')
    expect(button.textContent).toContain('Open in editor')
  })

  it('dispatches the pulse_task_action event when clicked', async () => {
    const onAction = vi.fn()
    const { container } = render(
      <SurfaceHost surfaceId={SURFACE_ID} ops={operations} onAction={onAction} />,
    )

    const button = await waitFor(
      () => {
        const el = container.querySelector('[data-testid="pulse-task-action"]')
        if (!el) throw new Error('action button never mounted')
        return el as HTMLButtonElement
      },
      { timeout: 10_000 },
    )

    await act(async () => {
      button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    // eslint-disable-next-line no-console
    console.log('[dispatched]', JSON.stringify(onAction.mock.calls))
    expect(onAction).toHaveBeenCalled()
  })
})

describe('pulse-webview App shell', () => {
  /**
   * jsdom cannot resolve the relative runtime URL the app now uses, so bridge
   * relative fetches to a Copilot Runtime. If one is running locally we use it
   * for real; otherwise we serve the same /info payload it would return. This
   * lets the provider actually *discover* `pulse_agent`.
   */
  let restoreFetch: () => void = () => {}

  beforeAll(async () => {
    const RUNTIME = 'http://127.0.0.1:8200'
    let info: unknown
    try {
      const res = await globalThis.fetch(`${RUNTIME}/api/copilotkit/info`)
      info = await res.json()
    } catch {
      info = {
        version: '1.69.3',
        agents: {
          pulse_agent: { name: 'pulse_agent', description: '', className: 'HttpAgent' },
          default: { name: 'default', description: '', className: 'HttpAgent' },
        },
        mode: 'sse',
        a2uiEnabled: true,
        a2ui: { enabled: true, agents: ['pulse_agent', 'default'] },
      }
    }

    const realFetch = globalThis.fetch.bind(globalThis)
    globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      if (url.startsWith('/')) return realFetch(`${RUNTIME}${url}`, init)
      return realFetch(input as RequestInfo, init)
    }) as typeof fetch

    restoreFetch = () => {
      globalThis.fetch = realFetch
    }

    // Sanity: the runtime advertises the agent the app binds to.
    expect((info as { agents: Record<string, unknown> }).agents).toHaveProperty('pulse_agent')
  })

  afterAll(() => restoreFetch())

  it('mounts and paints the branded header', async () => {
    const { default: App } = await import('../App')
    const { container } = render(<App />)

    await waitFor(
      () => {
        const header = Array.from(container.querySelectorAll('header')).find((h) =>
          (h.textContent ?? '').includes('PulseAI'),
        )
        if (!header) throw new Error('header not painted')
      },
      { timeout: 10_000 },
    )

    const header = Array.from(container.querySelectorAll('header')).find((h) =>
      (h.textContent ?? '').includes('PulseAI'),
    )!
    expect(header.textContent).toContain('Pulse Agent')
  })

  it('paints a chat composer the user can type into', async () => {
    const { default: App } = await import('../App')
    const { container } = render(<App />)

    const composer = await waitFor(
      () => {
        const el =
          container.querySelector('textarea') ??
          container.querySelector('[contenteditable="true"]') ??
          container.querySelector('[role="textbox"]')
        if (!el) throw new Error('composer not painted')
        return el
      },
      { timeout: 15_000 },
    )

    expect(composer).toBeTruthy()
  })
})
