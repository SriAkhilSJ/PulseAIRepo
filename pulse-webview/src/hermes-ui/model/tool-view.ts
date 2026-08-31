// Ported from hermes-agent `store/tool-view.ts` @ a9c783f2. Upstream uses
// nanostores atoms; this tier has no nanostores, so the same contract is a tiny
// external store (`useSyncExternalStore`) with the same caching rules:
//   - `$toolDisclosureOpen(id)` / `$anyToolDisclosureOpen(ids)` return a
//     MEMOIZED snapshot per id so a toggle only re-renders rows whose answer
//     changed — the reason upstream caches atoms.
//   - state persists to localStorage, capped at MAX_DISCLOSURE_STATES, and a
//     storage failure is not an error: it is a local UI preference.

import { useCallback, useSyncExternalStore } from 'react';

export type ToolViewMode = 'product' | 'technical';

type ToolDisclosureStates = Record<string, boolean>;

const TOOL_VIEW_TECHNICAL_STORAGE_KEY = 'pulse.webview.toolView.technical';
const TOOL_DISCLOSURE_STORAGE_KEY = 'pulse.webview.toolDisclosure.v1';
const MAX_DISCLOSURE_STATES = 240;

function readBoolean(key: string): boolean {
  try {
    return globalThis.localStorage?.getItem(key) === '1';
  } catch {
    return false;
  }
}

function loadToolDisclosureStates(): ToolDisclosureStates {
  try {
    const raw = globalThis.localStorage?.getItem(TOOL_DISCLOSURE_STORAGE_KEY);

    if (!raw) {
      return {};
    }

    const parsed = JSON.parse(raw) as unknown;

    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return {};
    }

    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>)
        .filter((entry): entry is [string, boolean] => typeof entry[0] === 'string' && typeof entry[1] === 'boolean')
        .slice(-MAX_DISCLOSURE_STATES)
    );
  } catch {
    return {};
  }
}

function persistToolDisclosureStates(states: ToolDisclosureStates) {
  try {
    const entries = Object.entries(states).slice(-MAX_DISCLOSURE_STATES);

    globalThis.localStorage?.setItem(TOOL_DISCLOSURE_STORAGE_KEY, JSON.stringify(Object.fromEntries(entries)));
  } catch {
    // Tool disclosure is a local UI preference; ignore storage failures.
  }
}

const listeners = new Set<() => void>();

let disclosureStates: ToolDisclosureStates = loadToolDisclosureStates();
let toolViewMode: ToolViewMode = readBoolean(TOOL_VIEW_TECHNICAL_STORAGE_KEY) ? 'technical' : 'product';
/** Rows the user dismissed out of a settled tail (upstream `$toolRowDismissed`). */
const dismissedRows = new Set<string>();

function emit() {
  for (const listener of listeners) {
    listener();
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);

  return () => listeners.delete(listener);
}

export function setToolViewMode(mode: ToolViewMode) {
  if (mode === toolViewMode) {
    return;
  }

  toolViewMode = mode;

  try {
    globalThis.localStorage?.setItem(TOOL_VIEW_TECHNICAL_STORAGE_KEY, mode === 'technical' ? '1' : '0');
  } catch {
    // Preference only.
  }

  emit();
}

export function useToolViewMode(): ToolViewMode {
  return useSyncExternalStore(subscribe, () => toolViewMode, () => toolViewMode);
}

const disclosureSnapshots = new Map<string, { open: boolean | undefined }>();

/** Stable per-id snapshot: `useSyncExternalStore` compares with Object.is, so a
 *  fresh object per read would re-render every row on every toggle. */
function disclosureSnapshot(id: string) {
  let snapshot = disclosureSnapshots.get(id);

  if (!snapshot || snapshot.open !== disclosureStates[id]) {
    snapshot = { open: disclosureStates[id] };
    disclosureSnapshots.set(id, snapshot);
  }

  return snapshot;
}

export function useToolDisclosureOpen(id: string, fallbackOpen = false): boolean {
  const snapshot = useSyncExternalStore(subscribe, () => disclosureSnapshot(id), () => disclosureSnapshot(id));

  return snapshot.open ?? fallbackOpen;
}

/** Whether any of a set of disclosures is open — a run asking about its rows.
 *  Computed per-id-set and memoized so a toggle elsewhere in the transcript
 *  only re-renders the runs whose own answer changed. */
const anyOpenSnapshots = new Map<string, { value: boolean }>();

function anyOpenSnapshot(ids: readonly string[]) {
  const key = ids.join('|');
  const value = ids.some(id => Boolean(disclosureStates[id]));
  const snapshot = anyOpenSnapshots.get(key);

  if (!snapshot || snapshot.value !== value) {
    const next = { value };

    anyOpenSnapshots.set(key, next);

    return next;
  }

  return snapshot;
}

export function useAnyToolDisclosureOpen(ids: readonly string[]): boolean {
  return useSyncExternalStore(subscribe, () => anyOpenSnapshot(ids), () => anyOpenSnapshot(ids)).value;
}

export function setToolDisclosureOpen(id: string, open: boolean) {
  if (!id || disclosureStates[id] === open) {
    return;
  }

  disclosureStates = { ...disclosureStates, [id]: open };
  persistToolDisclosureStates(disclosureStates);
  emit();
}

export function useToggleToolDisclosure(id: string): (open?: boolean) => void {
  return useCallback(
    (open?: boolean) => {
      setToolDisclosureOpen(id, open ?? !disclosureStates[id]);
    },
    [id]
  );
}

export function dismissToolRow(id: string) {
  if (dismissedRows.has(id)) {
    return;
  }

  dismissedRows.add(id);
  emit();
}

export function useToolRowDismissed(id: string): boolean {
  return useSyncExternalStore(
    subscribe,
    () => dismissedRows.has(id),
    () => dismissedRows.has(id)
  );
}

/** Test seam: disclosure state is module-level so it survives unmount/remount,
 *  which means a suite has to be able to reset it. */
export function __resetToolViewForTests() {
  disclosureStates = {};
  dismissedRows.clear();
  disclosureSnapshots.clear();
  anyOpenSnapshots.clear();
  toolViewMode = 'product';
  emit();
}
