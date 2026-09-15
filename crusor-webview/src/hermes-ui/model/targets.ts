// Ported verbatim (formatting only) from hermes-agent
// `tool/fallback-model/targets.ts` @ a9c783f2 — 74 lines, pure functions.

import type { ToolPart } from './types';

export function looksLikeUrl(value: string): boolean {
  return /^https?:\/\//i.test(value);
}

export function looksLikePath(value: string): boolean {
  return /^file:\/\//i.test(value) || /^(?:\/|\.{1,2}\/|~\/).+/.test(value);
}

/** Only local files and loopback URLs can be shown in the embedded preview —
 *  a remote URL belongs in the browser, not in the agent's own panel. */
export function isPreviewableTarget(target: string): boolean {
  return Boolean(
    target &&
      (/^file:\/\//i.test(target) ||
        /^(?:\/|\.{1,2}\/|~\/).+\.html?$/i.test(target) ||
        /^https?:\/\/(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])/i.test(target))
  );
}

export function stableHash(value: string): string {
  let hash = 0;

  for (let index = 0; index < value.length; index += 1) {
    hash = Math.imul(31, hash) + value.charCodeAt(index);
  }

  return Math.abs(hash).toString(36);
}

export function toolPartDisclosureId(part: ToolPart): string {
  if (part.toolCallId) {
    return `tool:${part.toolCallId}`;
  }

  return `tool:${part.toolName}:${stableHash(JSON.stringify(part.args ?? ''))}`;
}

export function toolGroupDisclosureId(parts: ToolPart[]): string {
  return `tool-group:${parts.map(toolPartDisclosureId).join('|')}`;
}

export const URL_PATTERN = /https?:\/\/[^\s'"<>)\]]+/i;

export function findFirstUrl(...sources: unknown[]): string {
  for (const src of sources) {
    if (typeof src === 'string') {
      const m = src.match(URL_PATTERN);

      if (m) {
        return m[0];
      }
    } else if (src && typeof src === 'object') {
      for (const v of Object.values(src as Record<string, unknown>)) {
        const found = findFirstUrl(v);

        if (found) {
          return found;
        }
      }
    }
  }

  return '';
}

export function hostnameOf(value: string): string {
  try {
    const url = new URL(value);

    return `${url.hostname}${url.pathname && url.pathname !== '/' ? url.pathname : ''}`;
  } catch {
    return value;
  }
}
