import { useState } from 'react'

import { CodeCard, CodeCardBody } from '@/components/chat/code-card'
import { ExpandableBlock } from '@/components/chat/expandable-block'
import { SCAFFOLD_GLYPH_CLASS, SCAFFOLD_LABEL_CLASS, SCAFFOLD_META_CLASS, ScaffoldRow } from '@/components/chat/scaffold-row'
import { Codicon } from '@/components/ui/codicon'

// Demo transcript rendering through the ported hermes chat components,
// mirroring the owner's field screenshots (the "list the files" turn) so
// card parity can be compared 1:1. The live bridge (turn frames -> props)
// lands on this same component surface next.
function ThinkingRow({ meta }: { meta: string }) {
  return (
    <div data-conversation-scaffold>
      <ScaffoldRow open={false}>
        <span className={SCAFFOLD_GLYPH_CLASS}>
          <Codicon name="lightbulb" size="0.75rem" className="text-(--conversation-scaffold-text)" />
        </span>
        <span className={SCAFFOLD_LABEL_CLASS}>Thought for a moment</span>
        <span className={SCAFFOLD_META_CLASS}>{meta}</span>
      </ScaffoldRow>
    </div>
  )
}

function ToolRunRow({ command, output, meta }: { command: string; output: string; meta: string }) {
  const [open, setOpen] = useState(true)
  return (
    <div data-conversation-scaffold>
      <div className="flex flex-col gap-(--tool-row-gap)">
        <ScaffoldRow open={open} onToggle={() => setOpen(v => !v)} trailing={<span className={SCAFFOLD_META_CLASS}>{meta}</span>}>
          <span className={SCAFFOLD_GLYPH_CLASS}>
            <Codicon name="terminal" size="0.75rem" className="text-(--conversation-scaffold-text)" />
          </span>
          <span className={SCAFFOLD_LABEL_CLASS}>Used {command}</span>
        </ScaffoldRow>
        {open && (
          <CodeCard>
            <ExpandableBlock>
              <CodeCardBody>
                <pre>{output}</pre>
              </CodeCardBody>
            </ExpandableBlock>
          </CodeCard>
        )}
      </div>
    </div>
  )
}

function QuestionCard({ title, question, options }: { title: string; question: string; options: string[] }) {
  return (
    <div className="pulseai-question-card" data-slot="pulseai-question-card">
      <div className="pulseai-question-title">
        <Codicon name="question" size="0.75rem" className="text-(--ui-accent)" />
        {title}
      </div>
      <div>{question}</div>
      <ul>
        {options.map(option => (
          <li key={option}>{option}</li>
        ))}
      </ul>
    </div>
  )
}

const DIR_OUTPUT = `src
docs
README.md
package.json
Exit code: 0`

export default function App() {
  return (
    <main className="pulseai-conversation" data-slot="pulseai-conversation">
      <div className="pulseai-turn" data-slot="pulseai-turn">
        <div className="pulseai-human">list the files</div>

        <div data-slot="pulseai_assistant-message-content" className="flex flex-col gap-(--turn-block-gap)">
          <ThinkingRow meta="1.2s" />

          <ToolRunRow command="cd D:\\pulseAIagent\\PulseAIRepo && dir /b" output={DIR_OUTPUT} meta="0.8s · exit 0" />

          <QuestionCard
            title="I need a bit more clarity:"
            question="Which directory would you like me to list files in?"
            options={[
              'The workspace root: D:\\pulseAIagent\\PulseAIRepo',
              'The current working directory (if different)',
              'A specific subfolder',
            ]}
          />

          <div className="pulseai-prose" data-slot="pulseai-prose">
            <p>
              Say <code>root</code> and I'll list it right away — or name any subfolder and I'll start
              there.
            </p>
          </div>
        </div>
      </div>
    </main>
  )
}
