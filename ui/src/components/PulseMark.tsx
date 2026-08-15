import type { Component } from "solid-js";

interface PulseMarkProps {
  compact?: boolean;
}

export const PulseMark: Component<PulseMarkProps> = (props) => (
  <div class="brand" aria-label="PulseAI IDE">
    <span class="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 32 32" fill="none">
        <rect x="1" y="1" width="30" height="30" rx="9" />
        <path d="M5 17h5l2.5-7 4.2 13 3.1-9 2.1 3H27" />
        <circle cx="27" cy="17" r="1.8" />
      </svg>
    </span>
    {!props.compact && (
      <span class="brand-word">
        Pulse<span>AI</span> <small>IDE</small>
      </span>
    )}
  </div>
);
