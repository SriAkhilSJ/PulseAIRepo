// Ported from hermes-agent `assistant-ui/thread/content.ts` @ a9c783f2.

const EMPTY_ATTACHMENT_REFS: string[] = [];

export function partText(part: unknown): string {
  if (typeof part === 'string') {
    return part;
  }

  if (!part || typeof part !== 'object') {
    return '';
  }

  const row = part as { text?: unknown; type?: unknown };

  return (!row.type || row.type === 'text') && typeof row.text === 'string' ? row.text : '';
}

export function messageContentText(content: unknown): string {
  if (typeof content === 'string') {
    return content.trim();
  }

  return Array.isArray(content) ? content.map(partText).join('').trim() : '';
}

/** Cheap streaming-stable "does this message have visible text" check: returns
 *  on the first non-whitespace text part without concatenating the whole
 *  message. Its boolean output stays stable across token flushes (flips
 *  false→true once per turn). */
export function contentHasVisibleText(content: unknown): boolean {
  if (typeof content === 'string') {
    return content.trim().length > 0;
  }

  if (!Array.isArray(content)) {
    return false;
  }

  for (const part of content) {
    if (partText(part).trim().length > 0) {
      return true;
    }
  }

  return false;
}

export function messageAttachmentRefs(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return EMPTY_ATTACHMENT_REFS;
  }

  return value.every(ref => typeof ref === 'string') ? value : EMPTY_ATTACHMENT_REFS;
}

/** Local dev-server URLs are the ones the user can actually click; prefer the
 *  first of them, else the last target the agent touched. */
export function pickPrimaryPreviewTarget(targets: string[]): string[] {
  if (targets.length <= 1) {
    return targets;
  }

  const localUrl = targets.find(value => /^https?:\/\/(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])/i.test(value));

  return [localUrl || (targets[targets.length - 1] as string)];
}

/** The tool calls of a message, in order — what the changed-files card and the
 *  activity rail both price off. Kept here so no component re-filters parts. */
export function deriveToolParts(message: { content: readonly { type: string }[] }): unknown[] {
  return message.content.filter(part => part.type === 'tool-call');
}
