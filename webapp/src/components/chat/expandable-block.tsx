import { type ReactNode, useCallback, useRef, useState } from 'react'

import { useResizeObserver } from '@/hooks/use-resize-observer'
import { Codicon } from '@/components/ui/codicon'
import { cn } from '@/lib/utils'

// Port: hermes apps/desktop/src/components/chat/expandable-block.tsx.
// Only deviation: hermes imports ChevronDown from @/lib/icons (a Tabler
// wrapper); here the same glyph comes from the vendored codicon font
// (`chevron-down`) so the website carries one icon system.
interface ExpandableBlockProps {
  children: ReactNode
  className?: string
}

export function ExpandableBlock({ children, className }: ExpandableBlockProps) {
  const innerRef = useRef<HTMLDivElement>(null)
  const [expanded, setExpanded] = useState(false)
  const [overflowing, setOverflowing] = useState(false)

  // Measure inside ResizeObserver timing only (layout is clean there). A
  // synchronous mount-time scrollHeight read forces a reflow per instance,
  // and a tool-heavy transcript mounts dozens of these on a session switch.
  const measure = useCallback(() => {
    const el = innerRef.current

    if (el) {
      setOverflowing(el.scrollHeight > 121)
    }
  }, [])

  useResizeObserver(measure, innerRef)

  return (
    <div className="relative">
      <div
        className={cn(
          'overflow-y-auto overflow-x-auto',
          expanded ? 'max-h-[40dvh]' : 'max-h-[7.5rem]',
          className
        )}
        ref={innerRef}
      >
        {children}
      </div>
      {overflowing && (
        // The fade is a pure overflow cue and must not intercept pointer events.
        // Keep it `pointer-events-none` and pin the only clickable target — a
        // compact toggle — to the right edge, clear of the scrollbar track.
        <div className="pointer-events-none absolute inset-x-0 bottom-0 flex h-7 justify-end bg-linear-to-t from-[var(--expandable-fade-from,var(--ui-chat-surface-background))] to-transparent">
          <button
            aria-expanded={expanded}
            aria-label={expanded ? 'Collapse' : 'Expand'}
            className="pointer-events-auto flex h-7 w-9 cursor-pointer items-end justify-center pb-1 text-muted-foreground/70 transition-colors hover:text-foreground"
            onClick={() => setExpanded(v => !v)}
            type="button"
          >
            <Codicon
              name="chevron-down"
              size="0.75rem"
              className={cn('transition-transform duration-150', expanded && 'rotate-180')}
            />
          </button>
        </div>
      )}
    </div>
  )
}
