import { cn } from '../lib/cn';

interface StableTextProps {
  children: string;
  className?: string;
}

/**
 * Renders text as a row of 1ch-wide cells so individual characters can't shift
 * the layout as they change (e.g. digits in a ticking timer). Works with any
 * proportional font — no need for font-mono.
 */
export function StableText({ children, className }: StableTextProps) {
  return (
    <span className={cn('pulse-stable-text', className)}>
      {children.split('').map((char, i) => (
        <span className="pulse-stable-text__cell" key={i}>
          {char}
        </span>
      ))}
    </span>
  );
}
