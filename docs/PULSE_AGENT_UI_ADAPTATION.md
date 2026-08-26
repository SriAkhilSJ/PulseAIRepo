# Pulse Agent UI adaptation

## Scope

This increment studies KiloCode at commit `99c621ee78b23c4538bd112bd8235d4722ca5ee9` as an interaction-design reference. It does **not** copy KiloCode branding, provider behavior, framework code, or application architecture. Pulse continues to use its shared, framework-neutral first-party renderer mounted by the existing Agent view and Pulse Manager editor.

## Patterns adapted

- **Clear session hierarchy:** the Agent header now gives the current task and workspace more visual weight while retaining native engine status and Manager navigation.
- **Readable conversation lane:** transcript content uses responsive gutters and a bounded line length in both the narrow Agent view and wide Manager editor.
- **Progressive disclosure:** plans and tool details stay compact and expandable; the plan's user-selected open state survives renderer updates within a session.
- **Stable activity dock:** live work has a dedicated status strip above approvals and the composer, so progress does not depend on transient transcript text.
- **Stronger empty state:** useful starter actions submit ordinary Pulse prompts through the existing host contract.
- **Composer as a dock:** the existing composer behavior is unchanged, but its focus, boundary, and visual separation are clearer.
- **Responsive and accessible behavior:** narrow layouts simplify secondary metadata, keyboard focus remains visible, and reduced-motion preferences disable nonessential animation.

## Preserved boundaries

- Pulse branding and semantic colors.
- Code OSS theme variables and native workbench conventions.
- Shared `pulseAIRenderer.ts` architecture for Agent and Manager.
- Existing safety approvals, cancellation, workspace gating, tool disclosure, and host methods.
- No provider/model request and no new telemetry or network behavior.

## Validation boundary

Provider-free structural tests, TypeScript syntax parsing, and the UI production build validate source integrity. They are not evidence of an interactive desktop runtime pass; that remains a separate Desktop-agent task.
