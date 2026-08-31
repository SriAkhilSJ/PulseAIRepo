import type { ReactNode } from 'react';

import { cn } from '../lib/cn';

// Shared header row for any collapsible block (thinking, tool group, single
// tool). Each parent supplies its own outer wrapper (with the data-slot CSS uses
// to escape the message padding) and its own expanded body.
//
// Affordance:
//   - No leading chevron; a caret appears to the RIGHT of the text on hover
//     (and stays visible when the row is open).
//   - The hover background is a tight content-shaped pill — sized to the title
//     text, NOT the full row — so it reads as a soft hit-target rather than a
//     slab stretching to the message edge.
//   - `trailing` stays in flow (e.g. a duration timer), so the title always
//     reserves space for it. Interactive controls go in `action`, which lays
//     out in flow at the far right so it never sits on the caret's hit-target.
export function DisclosureRow({
  action,
  children,
  onToggle,
  open,
  trailing,
}: {
  action?: ReactNode;
  children: ReactNode;
  onToggle?: () => void;
  open: boolean;
  trailing?: ReactNode;
}) {
  return (
    <div className="pulse-disclosure-row" data-open={open ? 'true' : 'false'}>
      <button
        aria-expanded={onToggle ? open : undefined}
        className={cn('pulse-disclosure-row__title', !onToggle && 'pulse-disclosure-row__title--static')}
        disabled={!onToggle}
        onClick={onToggle}
        type="button"
      >
        <span className="pulse-disclosure-row__stack">{children}</span>
        {onToggle && (
          <span className="pulse-disclosure-row__caret" data-open={open ? 'true' : 'false'}>
            ▾
          </span>
        )}
      </button>
      {action && <span className="pulse-disclosure-row__action">{action}</span>}
      {trailing && <span className="pulse-disclosure-row__trailing">{trailing}</span>}
    </div>
  );
}
