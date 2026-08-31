// Ported from hermes-agent `thread/list.tsx` (the pure half) @ a9c783f2.
//
// DOM is bounded by a render-cost budget, not a message/turn count. "Show
// earlier" prepends another page; whole turns stay intact so the sticky human
// bubble never loses its turn. This is the long-session perf lever WITHOUT a
// virtualizer — pure rendering, never touches scrollTop, so it can't fight
// stick-to-bottom (the single scroll owner).
//
// Upstream also shares the budget across simultaneously mounted panes
// (`$mountedTranscriptPanes`); this tier mounts one transcript per tree, so the
// single-pane budget is used directly and `transcriptPaneBudget` is kept for the
// iframe case where a host shows several embeds at once.

import type { PulseMessage } from '../pulse/types';
import { messagePaintWeight } from './render-weight';

/** 600 units ≈ 10-20 agentic turns on measured real sessions (a tool-heavy turn
 *  prices at 30-90, a plain exchange at 5-10). */
export const RENDER_BUDGET = 600;

/** Never offer "Show earlier" over fewer turns than this, however heavy they
 *  are: a weight-only cut on a session of enormous turns put the button two turns
 *  from the bottom, where it reads as broken rather than as paging. */
export const MIN_VISIBLE_GROUPS = 8;

/** On session switch, paint a small budget first (enough for the bottom turn(s)
 *  the user actually sees after scroll-to-bottom), then bump to the full budget
 *  in a requestAnimationFrame — defers the heavy markdown render past the
 *  initial commit, so the switch feels instant. 20, down from 60: the first-paint
 *  commit is synchronous and uninterruptible, and at 60 cost units it measured
 *  627ms on a real session. */
export const FIRST_PAINT_BUDGET = 20;

/** A hot-hidden transcript is retained for instant tab return, but keeping its
 *  full scrollback mounted defeats the bounded pane cache. */
export const HIDDEN_TRANSCRIPT_RENDER_BUDGET = 40;

/** Units the backfill adds per committed step. A 60-unit step produced ~10
 *  visible prepend frames; 290 fills a 600-unit page in two interruptible
 *  commits — still well under the measured 780ms single-jump freeze. */
export const BACKFILL_STEP = 290;

export const transcriptPaneBudget = (mountedPanes: number, hidden: boolean): number =>
  hidden ? HIDDEN_TRANSCRIPT_RENDER_BUDGET : Math.max(Math.ceil(RENDER_BUDGET / Math.max(1, mountedPanes)), RENDER_BUDGET / 4);

/** "Show earlier" raises renderBudget ABOVE paneBudget (one pane page per click).
 *  The render-phase cap must only snap a hot-hidden pane down to its retention
 *  budget — a visible pane's growth has to survive the next render or the click
 *  is a no-op. */
export const shouldClampTranscriptBudget = (hidden: boolean, renderBudget: number, paneBudget: number): boolean =>
  hidden && renderBudget > paneBudget;

export const transcriptBackfillFrameCount = (firstPaint = FIRST_PAINT_BUDGET, step = BACKFILL_STEP, budget = RENDER_BUDGET): number =>
  Math.ceil(Math.max(0, budget - firstPaint) / step);

export type MessageGroup = { id: string; weight: number } & ({ index: number; kind: 'standalone' } | { indices: number[]; kind: 'turn' });

/** Group each user message with the assistant turn(s) that follow it so the human
 *  bubble can stick against the scroller across its whole turn. */
export function buildGroups(entries: readonly { id: string; index: number; kind: 'assistant' | 'system' | 'user'; weight: number }[]): MessageGroup[] {
  const groups: MessageGroup[] = [];

  for (let i = 0; i < entries.length; i += 1) {
    const message = entries[i] as (typeof entries)[number];

    if (message.kind !== 'user') {
      groups.push({ id: message.id, index: message.index, kind: 'standalone', weight: message.weight });

      continue;
    }

    const indices = [message.index];
    let weight = message.weight;

    while (i + 1 < entries.length && (entries[i + 1] as (typeof entries)[number]).kind !== 'user') {
      weight += (entries[i + 1] as (typeof entries)[number]).weight;
      i += 1;
      indices.push((entries[i] as (typeof entries)[number]).index);
    }

    groups.push({ id: message.id, indices, kind: 'turn', weight });
  }

  return groups;
}

export function groupsFromMessages(messages: readonly PulseMessage[]): MessageGroup[] {
  return buildGroups(
    messages.map((message, index) => ({
      id: message.id,
      index,
      kind: message.role,
      weight: message.role === 'assistant' ? messagePaintWeight(message.content) : 1,
    }))
  );
}

/**
 * Walk turns newest-first, summing their render weights until the budget is met;
 * everything before the first kept turn is hidden. `minVisible` turns are kept
 * regardless of weight. Returns the index of that first visible group.
 */
export function firstVisibleGroupIndex(groups: readonly MessageGroup[], budget: number, minVisible = 0): number {
  let firstVisible = groups.length;

  for (let i = groups.length - 1, weight = 0; i >= 0; i -= 1) {
    weight += (groups[i] as MessageGroup).weight;
    firstVisible = i;

    if (weight >= budget) {
      break;
    }
  }

  return Math.min(firstVisible, Math.max(0, groups.length - minVisible));
}

/** `content-visibility: auto` skips off-screen turns, but with
 *  `contain-intrinsic-size: auto` the browser only remembers a turn's size AFTER
 *  it has rendered — so a turn that finishes streaming near the bottom can snap
 *  back to a stale height when it scrolls just off the top edge. With
 *  `overflow-anchor: none` the stick-to-bottom lock then drifts. Keeping the
 *  newest turns always-rendered means a turn is only virtualized once its layout
 *  has settled at its final size.
 *
 *  The tail is budgeted in render-cost units, not turns: a turn-count tail
 *  silently defeats itself on agent transcripts, where one tool-heavy turn is
 *  50-200 units, so a 6-TURN tail exempted the entire visible transcript and
 *  nothing virtualized at all. */
export const LIVE_TAIL_PARTS = 40;
export const LIVE_TAIL_MIN_GROUPS = 2;
export const LIVE_TAIL_MAX_GROUPS = 6;

/** Index of the newest group that still virtualizes — everything at or after it
 *  is the live tail and stays rendered. Computed once per render, not per row. */
export function liveTailStart(
  groups: readonly MessageGroup[],
  tailWeight = LIVE_TAIL_PARTS,
  minGroups = LIVE_TAIL_MIN_GROUPS,
  maxGroups = LIVE_TAIL_MAX_GROUPS
): number {
  let weight = 0;
  let start = groups.length;

  for (let i = groups.length - 1; i >= 0; i -= 1) {
    weight += (groups[i] as MessageGroup).weight;
    start = i;

    if (weight >= tailWeight) {
      break;
    }
  }

  const byWeight = Math.max(0, groups.length - maxGroups);
  const byMin = Math.max(0, groups.length - minGroups);

  return Math.min(Math.max(start, byWeight), byMin);
}
