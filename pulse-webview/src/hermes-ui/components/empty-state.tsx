// Ported from hermes-agent `components/ui/empty-state.tsx` (24 lines) plus the
// copy of `assistant-ui/chat-empty-slot.tsx`: an EMPTY transcript is a designed
// surface, not a blank div.
import type { ReactNode } from 'react';

import { cn } from '../lib/cn';

export function EmptyState({ children, className, title }: { children?: ReactNode; className?: string; title: string }) {
  return (
    <div className={cn('pulse-empty-state', className)} data-slot="pulse-empty-state">
      <p className="pulse-empty-state__title">{title}</p>
      {children && <div className="pulse-empty-state__body">{children}</div>}
    </div>
  );
}
