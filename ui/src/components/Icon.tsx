import type { Component } from "solid-js";

export type IconName =
  | "pulse" | "files" | "search" | "branch" | "terminal" | "settings"
  | "chevron" | "code" | "check" | "circle" | "lock" | "send" | "pause"
  | "folder" | "file" | "diff" | "clock" | "restore" | "shield" | "plus"
  | "test" | "warning" | "sparkles" | "panel" | "close" | "more"
  | "agent" | "sun" | "moon" | "play" | "copy";

const paths: Record<IconName, string> = {
  pulse: "M2 12h4l2.2-6 4.2 12 3.1-9 2.1 3H22",
  files: "M5 4h10l4 4v12H5z M15 4v5h4 M2 7v13h2",
  search: "M11 18a7 7 0 1 1 0-14 7 7 0 0 1 0 14m5-2 5 5",
  branch: "M6 3v12a4 4 0 0 0 4 4h5 M18 3v5a4 4 0 0 1-4 4H6 M3 6l3-3 3 3 M15 16l3 3-3 3",
  terminal: "M4 5h16v14H4z M7 9l3 3-3 3 M12 15h5",
  settings: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8m0-5v2m0 14v2M3 12h2m14 0h2M5.6 5.6 7 7m10 10 1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4",
  chevron: "m9 7 5 5-5 5",
  code: "m8 8-4 4 4 4m8-8 4 4-4 4m-2-11-4 14",
  check: "m5 12 4 4L19 6",
  circle: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18",
  lock: "M6 10h12v10H6z M8 10V7a4 4 0 0 1 8 0v3",
  send: "m3 4 18 8-18 8 4-8z M7 12h14",
  pause: "M8 5v14m8-14v14",
  folder: "M3 6h7l2 2h9v11H3z",
  file: "M6 3h8l4 4v14H6z M14 3v5h4",
  diff: "M7 3v18 M4 7l3-3 3 3 M17 21V3m-3 14 3 3 3-3",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18 M12 7v6l4 2",
  restore: "M4 4v6h6 M5 9a8 8 0 1 1 2 8",
  shield: "M12 3 5 6v5c0 5 3 8 7 10 4-2 7-5 7-10V6z M9 12l2 2 4-5",
  plus: "M12 5v14M5 12h14",
  test: "M9 3v5l-5 10a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3L15 8V3 M8 14h8",
  warning: "m12 3 10 18H2z M12 9v5m0 3v.01",
  sparkles: "m12 3 1.4 4.1L18 9l-4.6 1.9L12 15l-1.4-4.1L6 9l4.6-1.9z M19 15l.7 2.3L22 18l-2.3.7L19 21l-.7-2.3L16 18l2.3-.7z",
  panel: "M3 4h18v16H3z M15 4v16",
  close: "M6 6l12 12M18 6 6 18",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  agent: "M7 8h10a3 3 0 0 1 3 3v6a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3v-6a3 3 0 0 1 3-3 M12 3v5 M9 14h.01M15 14h.01 M9 17h6",
  sun: "M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10m0-5v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19",
  moon: "M20 15a8 8 0 0 1-11-11 9 9 0 1 0 11 11",
  play: "m8 5 11 7-11 7z",
  copy: "M8 8h11v12H8z M5 16H4V4h11v1",
};

interface IconProps {
  name: IconName;
  size?: number;
  class?: string;
  strokeWidth?: number;
}

export const Icon: Component<IconProps> = (props) => (
  <svg
    class={props.class ?? "icon"}
    width={props.size ?? 16}
    height={props.size ?? 16}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width={props.strokeWidth ?? 1.7}
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d={paths[props.name]} />
  </svg>
);
