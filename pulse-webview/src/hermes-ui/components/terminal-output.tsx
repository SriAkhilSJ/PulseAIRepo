import { useCallback, useEffect, useRef } from 'react';

import { cn } from '../lib/cn';

interface TerminalOutputProps {
  className?: string;
  text: string;
}

const NEAR_BOTTOM_PX = 24;

/**
 * Tiny read-only terminal viewer: monospace, non-wrapping (long lines scroll
 * horizontally), vertical scroll past `max-h`. Jumps to the bottom on mount,
 * then tails — sticking to the bottom as `text` grows, but only when the user
 * is already near the bottom so scrolling up to read earlier output isn't
 * interrupted.
 *
 * Self-contained so any surface (status rows, tool calls, inspectors) can drop
 * in a stdout/stderr box without re-implementing the scroll logic.
 */
export function TerminalOutput({ className, text }: TerminalOutputProps) {
  const ref = useRef<HTMLPreElement>(null);

  const nearBottom = useCallback(() => {
    const el = ref.current;

    if (!el) {
      return true;
    }

    return el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_PX;
  }, []);

  useEffect(() => {
    const el = ref.current;

    if (el && nearBottom()) {
      el.scrollTop = el.scrollHeight;
    }
  }, [text, nearBottom]);

  return (
    <pre className={cn('pulse-terminal', className)} data-testid="pulse-terminal-output" ref={ref}>
      {text}
    </pre>
  );
}
