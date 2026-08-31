// Ported from hermes-agent `thread/index.tsx`'s composer affordances (the parts
// the transcript itself needs: submit, stop, and the steer/queue split) bound to
// Pulse's real turn-control frames — `src/runtime/turn_control.py` exposes
// cancel / steer / queue, and the bridge accepts `{kind:'cancel'|'steer'|'queue'}`.
// The full fork composer (attachments, model picker, permission menu) stays the
// fork's; this is the minimum honest surface for an embedded webview.

import { useCallback, useState, type KeyboardEvent } from 'react';

import { cn } from '../lib/cn';
import type { RunSignals } from './status-line';

export interface PulseComposerProps {
  onQueue?: (text: string) => void;
  onSteer?: (text: string) => void;
  onStop?: () => void;
  onSubmit: (text: string) => void;
  signals: RunSignals;
}

export function PulseComposer({ onQueue, onSteer, onStop, onSubmit, signals }: PulseComposerProps) {
  const [value, setValue] = useState('');
  const busy = signals.busy;

  const send = useCallback(
    (mode: 'queue' | 'send' | 'steer') => {
      const text = value.trim();

      if (!text) {
        return;
      }

      if (mode === 'queue' && onQueue) {
        onQueue(text);
      } else if (mode === 'steer' && onSteer) {
        onSteer(text);
      } else {
        onSubmit(text);
      }

      setValue('');
    },
    [onQueue, onSteer, onSubmit, value]
  );

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey) {
      return;
    }

    event.preventDefault();
    // While the agent is working, Enter STEERS (the turn adopts the line); a
    // ⌘/Ctrl+Enter queues it for after the turn, matching the fork's behavior.
    send(event.metaKey || event.ctrlKey ? 'queue' : busy ? 'steer' : 'send');
  };

  return (
    <div className="pulse-composer" data-slot="pulse-composer">
      <textarea
        aria-label="Message Pulse"
        className="pulse-composer__input"
        onChange={event => setValue(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder={busy ? 'Type to steer the current turn' : 'Ask Pulse to change something'}
        rows={2}
        value={value}
      />
      <div className="pulse-composer__actions">
        {busy ? (
          <button className="pulse-composer__stop" onClick={() => onStop?.()} type="button">
            Stop
          </button>
        ) : null}
        <button
          className={cn('pulse-composer__send', !value.trim() && 'pulse-composer__send--idle')}
          disabled={!value.trim()}
          onClick={() => send(busy ? 'steer' : 'send')}
          type="button"
        >
          {busy ? 'Steer' : 'Send'}
        </button>
      </div>
    </div>
  );
}
