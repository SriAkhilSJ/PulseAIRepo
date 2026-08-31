// The integration point that makes the port actually SHOW UP in the CopilotKit
// tier: `useDefaultRenderTool` registers a wildcard ("*") tool-call renderer, so
// every tool call CopilotChat would paint with its own generic card is painted
// with the ported `PulseToolRow` instead — same header/body/disclosure rules the
// fork uses, no fork edit.
//
// `useRenderTool({name})` remains available for per-tool cards; this file only
// claims the fallback slot, which is exactly the slot upstream's
// `ToolFallback` occupies.

import { useDefaultRenderTool } from '@copilotkit/react-core/v2';

import type { ToolPart } from '../model/types';
import { PulseToolRow } from '../components/tool-card';

export interface PulseToolRendererProps {
  /** Rows are keyed per tool call: an id scoped to the call means the disclosure
   *  state survives CopilotChat re-mounting the row (a re-render of the parent
   *  list must not collapse a diff someone opened). */
  disclosureScope?: string;
}

export function usePulseToolRenderer({ disclosureScope = 'copilotchat' }: PulseToolRendererProps = {}) {
  useDefaultRenderTool(
    {
      render: props => {
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
          <PulseToolRow
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
