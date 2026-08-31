// Public surface of the Pulse port of the Hermes desktop Agent UI.
//
// Everything here is provider-free: the components take a `PulseTranscript`, so
// a test (or a Storybook, or the fork's iframe harness) can render a whole turn
// with no CopilotKit runtime, no network and no API key. `usePulseThread` is the
// only piece that touches CopilotKit, and `usePulseTranscript` is the same logic
// with the agent passed in.
//
// Provenance: see src/prompts/hermes/PROVENANCE.md (same pin as the prompt
// engine: NousResearch/hermes-agent @ a9c783f2).

export { PulseAgentThread, PulseAssistantMessage, PulseSystemMessage, PulseUserMessage } from './components/thread';
export type { PulseAgentThreadProps, PulseAssistantMessageProps } from './components/thread';
export { PulseComposer } from './components/composer';
export { PulseToolRow, CopyButton, ApprovalContext, ToolEmbedContext } from './components/tool-card';
export { ApprovalRow, APPROVAL_TOOLS, approvalBlocksTool, commandFromArgs } from './components/approval-row';
export type { ApprovalChoice } from './components/approval-row';
export { PulseToolGroup, ToolRun, splitRunItems, computeToolRun } from './components/tool-run';
export { ResponseLoadingIndicator, RunStatusPanel, TurnActivityIndicator, ScaffoldStatus, useStatusHint, DRAFTING_REVEAL_MS, COMPACTION_LABEL } from './components/status-line';
export { ChangedFilesCard, MAX_CHANGED_FILE_ROWS } from './components/changed-files-card';
export { DisclosureRow } from './components/disclosure-row';
export { ScaffoldRow, SCAFFOLD_GLYPH_CLASS, SCAFFOLD_LABEL_CLASS, SCAFFOLD_META_CLASS } from './components/scaffold-row';
export { ExpandableBlock, EXPANDABLE_COLLAPSED_PX } from './components/expandable-block';
export { StatusRow } from './components/status-row';
export { StableText } from './components/stable-text';
export { TerminalOutput } from './components/terminal-output';
export { ToolRunTicker } from './components/run-ticker';
export { MarkdownText, splitMarkdownBlocks } from './components/markdown-text';
export { DiffBody, DiffCount, DIFF_KIND_TINT, FileDiffPanel, parseDiff, stripDiffFileHeaders } from './components/diff-lines';
export { EmptyState } from './components/empty-state';
export { resolveShowEarlierAction, TranscriptWindowProvider, useTranscriptWindow } from './components/transcript-window';

export { usePulseThread, usePulseTranscript } from './pulse/use-pulse-thread';
export type { PulseAgentLike, UsePulseTranscriptResult } from './pulse/use-pulse-thread';
export { usePulseToolRenderer } from './pulse/render-tools';
export { emptyTranscript, reducePulseEvent, transcriptFromMessages } from './pulse/normalize';
export type { PulseApproval, PulseMessage, PulseMessagePart, PulsePlanStep, PulseRunState, PulseSubAgent, PulseTextPart, PulseToolCallPart, PulseTranscript } from './pulse/types';

export { activitySignature, toolNarratesWait, TURN_QUIET_S } from './model/turn-activity';
export { summarizeToolRun, toolPresentVerb } from './model/run-summary';
export { deriveChangedFiles } from './model/changed-files';
export { activeTimelineIndex, deriveTimelineEntries, sameTimelineEntries, timelinePreview } from './model/timeline-data';
export { contentHasVisibleText, deriveToolParts, messageAttachmentRefs, messageContentText, pickPrimaryPreviewTarget } from './model/content';
export {
  BACKFILL_STEP,
  FIRST_PAINT_BUDGET,
  LIVE_TAIL_PARTS,
  MIN_VISIBLE_GROUPS,
  RENDER_BUDGET,
  firstVisibleGroupIndex,
  groupsFromMessages,
  liveTailStart,
  shouldClampTranscriptBudget,
  transcriptBackfillFrameCount,
  transcriptPaneBudget,
} from './model/render-budget';
export { messagePaintWeight, messageStoreWeight, payloadCharacters } from './model/render-weight';
export { MAX_TOOL_RENDER_CHARS, clampForDisplay, compactPreview, formatDurationSeconds, parseMaybeObject, prettyJson, unwrapToolPayload } from './model/format';
export { findFirstUrl, hostnameOf, isPreviewableTarget, looksLikePath, looksLikeUrl, stableHash, toolGroupDisclosureId, toolPartDisclosureId } from './model/targets';
export { buildToolView, isCardTool, isFileEditTool, isSilentTool, looksRedundant, stripInlineDiffChrome, toolCopyPayload } from './model/fallback-model';
export { dismissToolRow, setToolDisclosureOpen, setToolViewMode, useAnyToolDisclosureOpen, useToolDisclosureOpen, useToolRowDismissed, useToolViewMode, __resetToolViewForTests } from './model/tool-view';
export { __resetElapsedTimerRegistryForTests, formatElapsed, useElapsedSeconds, useMeasuredDuration } from './model/activity-timer';
export type { ToolPart, ToolStatus, ToolView } from './model/types';
