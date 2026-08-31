// Port of hermes-agent `hooks/use-resize-observer.ts`: measurement runs inside
// ResizeObserver timing only. A synchronous mount-time scrollHeight read forces
// a reflow per instance, and a tool-heavy transcript mounts dozens of these on
// a session switch.
import { useEffect, type RefObject } from 'react';

export function useResizeObserver(callback: () => void, ref: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const element = ref.current;

    if (!element || typeof ResizeObserver === 'undefined') {
      callback();

      return;
    }

    let frame = 0;

    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(callback);
    });

    observer.observe(element);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [callback, ref]);
}
