import { For, createMemo, type Component } from "solid-js";
import { NativeMenuBar } from "../components/DropdownMenu";
import { Icon } from "../components/Icon";
import { ToolRow } from "../components/ToolRow";
import { PULSE_TOOL_CATALOG, type ToolRendererFamily } from "../runtime/toolCatalog";
import { TOOL_FAMILY_SAMPLES } from "../runtime/toolSamples";

const familyOrder: readonly ToolRendererFamily[] = [
  "control", "file-read", "file-write", "search", "terminal", "process",
  "code", "verification", "web", "browser", "session", "subagent", "scaffold",
];

export const ToolGallerySurface: Component = () => {
  const groups = createMemo(() => familyOrder.map((family) => ({
    family,
    tools: Object.entries(PULSE_TOOL_CATALOG).filter(([, item]) => item.family === family),
  })).filter((group) => group.tools.length > 0));

  return (
    <div class="tool-gallery-shell">
      <NativeMenuBar title="Tool Renderer Gallery — PulseAI IDE" />
      <aside class="tool-gallery-index">
        <header><span class="eyebrow">UI LAB</span><h2>Tool catalog</h2><p>34 runtime tools</p></header>
        <div class="tool-family-list">
          <For each={groups()}>{(group) => (
            <section>
              <h3>{group.family}</h3>
              <For each={group.tools}>{([name, item]) => <button type="button"><Icon name={item.icon} size={12} /><span>{item.title}</span><code>{name}</code></button>}</For>
            </section>
          )}</For>
        </div>
      </aside>

      <main class="tool-gallery-main">
        <header class="tool-gallery-heading">
          <div><span class="eyebrow">RENDERER FAMILIES</span><h1>Expandable tool disclosures</h1></div>
          <p>Flat transcript rows. Expand only when useful details exist. Terminal opens by default.</p>
        </header>
        <div class="tool-gallery-list">
          <For each={TOOL_FAMILY_SAMPLES}>{(sample) => <ToolRow tool={sample} />}</For>
        </div>
      </main>

      <aside class="tool-gallery-notes">
        <header><span class="eyebrow">POLICY</span><h2>Disclosure rules</h2></header>
        <dl>
          <div><dt>Terminal</dt><dd>Open by default</dd></div>
          <div><dt>Running task</dt><dd>Open while active</dd></div>
          <div><dt>Edit/write</dt><dd>User preference</dd></div>
          <div><dt>Error</dt><dd>Open with receipt</dd></div>
          <div><dt>Queued</dt><dd>Locked</dd></div>
          <div><dt>Completed</dt><dd>Closed unless reopened</dd></div>
        </dl>
        <section>
          <h3>Performance</h3>
          <p>Expanded bodies will mount lazily. Long terminal output, diffs and browser snapshots are bounded and virtualized by the production renderer.</p>
        </section>
      </aside>
    </div>
  );
};
