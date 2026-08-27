# Pulse Agent UI adaptation

## Scope

This increment studies KiloCode at commit `99c621ee78b23c4538bd112bd8235d4722ca5ee9` as an interaction-design reference. It does **not** copy KiloCode branding, provider behavior, framework code, or application architecture. Pulse continues to use its shared, framework-neutral first-party renderer mounted by the existing Agent view and Pulse Manager editor.

## Patterns adapted

- **Clear session hierarchy:** the Agent header now gives the current task and workspace more visual weight while retaining native engine status and Manager navigation.
- **Readable conversation lane:** transcript content uses responsive gutters and a bounded line length in both the narrow Agent view and wide Manager editor.
- **Progressive disclosure:** plans and tool details stay compact and expandable; the plan's user-selected open state survives renderer updates within a session.
- **Stable activity dock:** live work has a dedicated status strip above approvals and the composer, so progress does not depend on transient transcript text.
- **Stronger empty state:** useful starter actions submit ordinary Pulse prompts through the existing host contract. Typography inherits the workbench scale and all colors come from Code OSS theme tokens.
- **Functional execution modes:** the composer offers Agent, Plan, Debug, and Ask through one accessible native menu. The selected mode travels over the versioned bridge protocol; Plan previews without execution, Ask binds no tools, Debug adds diagnosis-first runtime policy, and Agent retains the full guarded workflow.
- **Composer as a dock:** the existing context, submit, stop, and workspace behavior remains intact, while focus, boundary, and visual separation are clearer.
- **Responsive and accessible behavior:** narrow layouts simplify secondary metadata, keyboard focus remains visible, and reduced-motion preferences disable nonessential animation.

## Preserved boundaries

- Pulse branding and semantic colors.
- Code OSS theme variables and native workbench conventions.
- Shared `pulseAIRenderer.ts` architecture for Agent and Manager.
- Existing safety approvals, cancellation, workspace gating, tool disclosure, and host methods.
- No provider/model request and no new telemetry or network behavior.

## Validation boundary

The original Agent/Manager layout passed provider-free compile and CDP runtime validation through evidence `43cf8296`. Execution-mode changes require a fresh provider-free protocol/build/CDP validation; no provider call is needed or authorized.
