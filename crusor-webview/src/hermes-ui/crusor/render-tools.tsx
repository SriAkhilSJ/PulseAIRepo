// The integration point that makes the port actually SHOW UP in the CopilotKit
// tier: `useDefaultRenderTool` registers a wildcard ("*") tool-call renderer, so
// every tool call CopilotChat would paint with its own generic card is painted
// with the ported `CrusorToolRow` instead — same header/body/disclosure rules the
// fork uses, no fork edit.
//
// `useRenderTool({name})` remains available for per-tool cards; this file only
// claims the fallback slot, which is exactly the slot upstream's
// `ToolFallback` occupies.

import { useDefaultRenderTool } from '@copilotkit/react-core/v2';

import type { ToolPart } from '../model/types';
import { CrusorToolRow } from '../components/tool-card';

export interface CrusorToolRendererProps {
  /** Rows are keyed per tool call: an id scoped to the call means the disclosure
   *  state survives CopilotChat re-mounting the row (a re-render of the parent
   *  list must not collapse a diff someone opened). */
  disclosureScope?: string;
}

export function useCrusorToolRenderer({ disclosureScope = 'copilotchat' }: CrusorToolRendererProps = {}) {
  useDefaultRenderTool(
    {
      render: props => {
        // OpenCode parity: delegate_to_subagent renders as TaskToolCard
        if (props.name === 'delegate_to_subagent' || props.name === 'delegate_to_subagent_batch') {
          try {
            const args: any = props.parameters || {};
            const description = args.description || args.task || args.prompt || '';
            const subagentType = args.subagent_type || args.mode || 'general';
            const background = !!args.background;
            // Try to parse result for session id
            let sessionId = '';
            let status = props.status === 'complete' ? 'completed' : 'running';
            let toolCalls: number | undefined;
            if (typeof props.result === 'string') {
              const m = props.result.match(/Agent ID:\s*([^\s*]+)/) || props.result.match(/id="([^"]+)"/);
              if (m) sessionId = m[1];
              if (props.result.includes('Background task started')) status = 'running';
            } else if (props.result && typeof props.result === 'object') {
              const r: any = props.result;
              sessionId = r.sessionId || r.child_thread_id || r.subagent_id || '';
              if (r.toolCalls || r.tool_calls) toolCalls = r.toolCalls || r.tool_calls;
            }
            const color = (() => {
              const palette = ['#0b6bcb', '#8b5cf6', '#10b981', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#84cc16'];
              let hash = 0;
              const name = String(subagentType || '');
              for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
              return palette[hash % palette.length];
            })();
            return (
              <div
                data-component="task-tool-card"
                data-testid="task-tool-card"
                style={{ ['--task-agent-color' as any]: color, display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', borderRadius: 6, border: '1px solid #e5e7eb', background: '#fff', cursor: sessionId ? 'pointer' : 'default' } as any}
                onClick={sessionId ? () => {
                  try {
                    const ev = new CustomEvent('crusorai:navigate-to-session', { detail: { sessionId } });
                    window.dispatchEvent(ev);
                  } catch {}
                } : undefined}
              >
                <span style={{ color, fontSize: 12 }}>{status === 'running' ? '◍' : '●'}</span>
                <span style={{ fontWeight: 600, textTransform: 'capitalize', color, fontSize: 12 }}>{subagentType}</span>
                <span style={{ fontSize: 12, color: '#6b7280', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                  {description}{background ? ' (background)' : ''}{toolCalls ? ` · ${toolCalls} calls` : ''}
                </span>
                {sessionId && <span style={{ fontSize: 11, opacity: 0.6 }}>↗</span>}
              </div>
            );
          } catch {}
        }

        const part: ToolPart = {
          args: props.parameters,
          // Only a complete call carries a result; anything earlier stays pending
          // so the row shows its timer and the run keeps its ticker.
          result: props.status === 'complete' ? props.result : undefined,
          toolCallId: props.toolCallId,
          toolName: props.name,
          type: 'tool-call',
        };

        return (
          <CrusorToolRow
            messageRunning={props.status !== 'complete'}
            messageId={disclosureScope}
            part={part}
          />
        );
      },
    },
    [disclosureScope]
  );
}
