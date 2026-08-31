// Local stand-in for the upstream `@/lib/utils` cn() (clsx + tailwind-merge).
// Pulse's webview styles with plain CSS classes, so composition is a join.
export type ClassValue = string | false | null | undefined;

export function cn(...values: ClassValue[]): string {
  return values.filter(Boolean).join(' ');
}
