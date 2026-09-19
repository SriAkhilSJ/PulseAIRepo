// Ported from hermes-agent `apps/desktop/src/components/ui/status-pulse.tsx` @ a9c783f2
// Preserves Crusor color design: uses currentColor / CSS variables unchanged,
// only changes animation mechanism from infinite CSS (1.6s) to finite Web Animations
// pulse every 5s so renderer can sleep between beats — fixes vibration/lag.

import { useEffect, useRef } from 'react';

const PULSE_DURATION_MS = 400;
const PULSE_PERIOD_MS = 5_000;

type PulseSubscriber = { play: () => void; cancel: () => void };
const pulseSubscribers = new Set<PulseSubscriber>();
let sharedTimer = 0;

const stopSharedTimer = () => {
  if (sharedTimer !== 0) {
    window.clearTimeout(sharedTimer);
    sharedTimer = 0;
  }
};

const beat = () => {
  sharedTimer = 0;
  if (pulseSubscribers.size === 0) return;
  // pause when hidden/minimized — save CPU for pixels nobody sees
  if (document.visibilityState === 'hidden' || !document.hasFocus()) return;
  for (const s of pulseSubscribers) s.play();
  sharedTimer = window.setTimeout(beat, PULSE_PERIOD_MS);
};

const subscribePulse = (subscriber: PulseSubscriber): (() => void) => {
  pulseSubscribers.add(subscriber);
  if (sharedTimer === 0 && document.visibilityState !== 'hidden') {
    subscriber.play();
    sharedTimer = window.setTimeout(beat, PULSE_PERIOD_MS);
  }
  return () => {
    pulseSubscribers.delete(subscriber);
    if (pulseSubscribers.size === 0) stopSharedTimer();
  };
};

export function StatusPulse({
  className,
  ...props
}: React.ComponentPropsWithoutRef<'span'> & { kind?: 'opacity' | 'ping' }) {
  const ref = useRef<HTMLSpanElement>(null);
  const kind = (props as { kind?: string }).kind ?? 'opacity';

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof el.animate !== 'function') return;
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;

    let animation: Animation | null = null;

    const play = () => {
      animation?.cancel();
      animation = el.animate(
        kind === 'ping'
          ? [{ opacity: 1, transform: 'scale(1)' }, { opacity: 0, transform: 'scale(2)' }]
          : [{ opacity: 1 }, { opacity: 0.5 }, { opacity: 1 }],
        { duration: PULSE_DURATION_MS, easing: 'ease-in-out', iterations: 1 }
      );
    };
    const cancel = () => {
      animation?.cancel();
      animation = null;
    };

    const unsubscribe = subscribePulse({ play, cancel });
    return () => {
      unsubscribe();
      cancel();
    };
  }, [kind]);

  return <span ref={ref} {...props} className={className} />;
}
