import { type KeyboardEvent, type MouseEvent, type ReactNode, type Ref } from 'react';

import { cn } from '../lib/cn';

interface StatusRowProps {
  children: ReactNode;
  className?: string;
  /** Leading glyph slot (spinner / status dot / selection circle). */
  leading?: ReactNode;
  /** Makes the whole row activatable (adds `cursor-pointer` + keyboard a11y).
   *  Receives the originating event so consumers can branch on modifier keys
   *  (e.g. ⌘/Ctrl-click). Trailing-slot buttons should `stopPropagation` so
   *  they don't also fire it. */
  onActivate?: (event: KeyboardEvent | MouseEvent) => void;
  /** Right-aligned actions. Revealed on row hover/focus unless `trailingVisible`. */
  trailing?: ReactNode;
  trailingVisible?: boolean;
  /** Forwarded to the row's root — lets a wrapper attach ref / onContextMenu to
   *  the real DOM node. */
  ref?: Ref<HTMLDivElement>;
  onContextMenu?: (event: MouseEvent) => void;
}

/**
 * Shared row chrome for everything in the composer status stack — status items
 * (subagents, background work) AND queued prompts. Fixed height, a leading
 * glyph slot, flexible content, and a trailing actions slot that reveals on
 * hover. Consumers fill the three slots; they never re-implement the row.
 */
export function StatusRow({ children, className, leading, onActivate, onContextMenu, ref, trailing, trailingVisible = false }: StatusRowProps) {
  return (
    <div
      className={cn('pulse-status-row', onActivate && 'pulse-status-row--activatable', className)}
      onClick={onActivate}
      onContextMenu={onContextMenu}
      onKeyDown={
        onActivate
          ? event => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                onActivate(event);
              }
            }
          : undefined
      }
      ref={ref}
      role={onActivate ? 'button' : undefined}
      tabIndex={onActivate ? 0 : undefined}
    >
      {leading !== undefined && <span className="pulse-status-row__leading">{leading}</span>}
      <div className="pulse-status-row__body">{children}</div>
      {trailing && <div className={cn('pulse-status-row__trailing', !trailingVisible && 'pulse-status-row__trailing--reveal')}>{trailing}</div>}
    </div>
  );
}
