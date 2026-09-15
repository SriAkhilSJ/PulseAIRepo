import { type ReactNode, useCallback, useRef, useState } from 'react';

import { cn } from '../lib/cn';
import { useResizeObserver } from '../lib/use-resize-observer';

interface ExpandableBlockProps {
  children: ReactNode;
  className?: string;
}

/** Collapsed height budget, in px — upstream's `max-h-[7.5rem]`. */
export const EXPANDABLE_COLLAPSED_PX = 121;

export function ExpandableBlock({ children, className }: ExpandableBlockProps) {
  const innerRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflowing, setOverflowing] = useState(false);

  const measure = useCallback(() => {
    const el = innerRef.current;

    if (el) {
      setOverflowing(el.scrollHeight > EXPANDABLE_COLLAPSED_PX);
    }
  }, []);

  useResizeObserver(measure, innerRef);

  return (
    <div className="crusor-expandable">
      <div
        className={cn('crusor-expandable__scroll', expanded && 'crusor-expandable__scroll--expanded', className)}
        data-expanded={expanded ? 'true' : 'false'}
        ref={innerRef}
      >
        {children}
      </div>
      {overflowing && (
        // The fade is a pure overflow cue and must not intercept pointer events:
        // it spans the full bottom edge (over the horizontal scrollbar of a wide
        // code block AND the block's last line), so making it clickable killed
        // both sideways scrolling and text selection. The only clickable target
        // is the compact toggle, pinned to the right edge.
        <div className="crusor-expandable__fade">
          <button
            aria-expanded={expanded}
            aria-label={expanded ? 'Collapse' : 'Expand'}
            className="crusor-expandable__toggle"
            onClick={() => setExpanded(value => !value)}
            type="button"
          >
            {expanded ? '▴' : '▾'}
          </button>
        </div>
      )}
    </div>
  );
}
