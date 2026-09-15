// Canonical text micro-helpers. Ported verbatim from hermes-agent
// apps/desktop/src/lib/text.ts @ a9c783f2 — do not redefine these per-surface.

export const asText = (v: unknown): string => (typeof v === 'string' ? v : v == null ? '' : String(v));

export const includesQuery = (v: unknown, q: string) => asText(v).toLowerCase().includes(q);

export const prettyName = (v: string) => v.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

/** Search-key normalization: the exact `value.trim().toLowerCase()` idiom. */
export const normalize = (v: unknown): string => asText(v).trim().toLowerCase();

/** Uppercase the first character, leave the rest (empty-safe). */
export const capitalize = (v: string): string => (v ? v.charAt(0).toUpperCase() + v.slice(1) : v);

/** First non-empty string among `keys`, trimmed. For reading tool args and
 *  results, where the key carrying the interesting value varies by tool. */
export const firstStringField = (record: Record<string, unknown>, keys: readonly string[]): string => {
  for (const key of keys) {
    const value = record[key];

    if (typeof value === 'string' && value.trim()) {
      return value.trim();
    }
  }

  return '';
};
