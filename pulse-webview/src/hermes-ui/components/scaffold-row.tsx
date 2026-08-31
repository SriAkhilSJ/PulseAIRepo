// Ported from hermes-agent `components/chat/scaffold-row.tsx` @ a9c783f2.
//
// Transcript scaffolding: the quiet lines around the reply that say what the
// agent did rather than what it said — a thinking header, a settled tool run,
// the live activity ticker. They all render through here so they cannot drift
// apart; upstream's note is that each used to pick its own grey and the two
// shades read as two kinds of line for one kind of thing.
//
// The resting fade lives in CSS on the *block* that holds the row — mark it
// `data-conversation-scaffold`. A surface that skips the mark reads a shade
// brighter than its neighbours.

import type { ReactNode } from 'react';

import { cn } from '../lib/cn';
import { DisclosureRow } from './disclosure-row';

export const SCAFFOLD_LABEL_CLASS = 'pulse-scaffold-label';
export const SCAFFOLD_META_CLASS = 'pulse-scaffold-meta';
export const SCAFFOLD_GLYPH_CLASS = 'pulse-scaffold-glyph';

/** One scaffold line. `children` is the label and whatever trails it in flow
 *  (meta, diff counts); `trailing` reserves a right-side slot for a live timer. */
export function ScaffoldRow({
  children,
  onToggle,
  open = false,
  trailing
}: {
  children: ReactNode;
  onToggle?: () => void;
  open?: boolean;
  trailing?: ReactNode;
}) {
  return (
    <DisclosureRow onToggle={onToggle} open={open} trailing={trailing}>
      <span className={cn('pulse-scaffold-line')}>{children}</span>
    </DisclosureRow>
  );
}
