// Crusor One-Shot — quick jobs outside the conversation (Phase 3).
// Command Palette: "Crusor: One-Shot Task" — pick a template (or ad-hoc),
// give it the input, one cheap-tier provider call, result to clipboard +
// notification. Stateless by contract: never appends to the thread, never
// touches the prompt cache.
import { localize2 } from '../../../../nls.js';
import { registerAction2, Action2 } from '../../../../platform/actions/common/actions.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IQuickInputService } from '../../../../platform/quickinput/common/quickInput.js';
import { IClipboardService } from '../../../../platform/clipboard/common/clipboardService.js';
import { IProgressService } from '../../../../platform/progress/common/progress.js';
import { ICrusorAIRendererService } from '../common/crusorAIRendererService.js';
const ONESHOT_TIMEOUT_MS = 60000;
function oneshotRequest(renderer, progress, template, extra) {
    return progress.withProgress({ location: 10 /* ProgressLocation.Window */, title: 'Crusor one-shot…' }, () => new Promise((resolve, reject) => {
        let listener;
        const timer = setTimeout(() => {
            listener?.dispose();
            reject(new Error(`One-shot: the engine did not answer the '${template}' request. Fully restart CrusorAI so the bridge runs this build.`));
        }, ONESHOT_TIMEOUT_MS);
        listener = renderer.onOneshotResult(frame => {
            clearTimeout(timer);
            listener?.dispose();
            resolve(frame);
        });
        renderer.sendOneshot(template, extra);
    }));
}
registerAction2(class extends Action2 {
    constructor() {
        super({
            id: 'crusorai.oneshot',
            title: localize2('crusorAI.oneshot', 'One-Shot Task'),
            f1: true,
            category: localize2('crusorAI.category', 'Crusor'),
        });
    }
    async run(accessor) {
        // ServicesAccessor is single-shot: every get() runs before the first await.
        const quickInput = accessor.get(IQuickInputService);
        const notif = accessor.get(INotificationService);
        const clipboard = accessor.get(IClipboardService);
        const progress = accessor.get(IProgressService);
        const renderer = accessor.get(ICrusorAIRendererService);
        const picks = [
            { label: '$(git-commit) Draft commit message', description: 'from a diff or a description of what changed', id: 'commit_message', variablePrompt: 'Paste the diff (or describe the change)' },
            { label: '$(book) Summarize', description: 'the essentials of a page or a document', id: 'summarize', variablePrompt: 'Paste the text to summarize' },
            { label: '$(lightbulb) Name ideas', description: '8 candidates with a one-clause rationale each', id: 'rename_ideas', variablePrompt: 'What needs a name? (feature, module, product…)' },
            { label: '$(symbol-string) Ad-hoc one-shot…', description: 'your own instruction + input — no thread, no cache cost', id: '__adhoc' },
        ];
        const pick = await quickInput.pick(picks, { placeHolder: 'Crusor One-Shot — one question, one answer, nothing saved to the chat' });
        if (!pick) {
            return;
        }
        let variables = {};
        let template = pick.id;
        if (pick.id === '__adhoc') {
            const ask = await quickInput.input({ prompt: 'What should the model do? (one instruction)' });
            if (!ask || !ask.trim()) {
                return;
            }
            const input = await quickInput.input({ prompt: 'Paste the input text (Enter to skip)' });
            template = 'adhoc';
            variables = { instructions: ask.trim(), input: (input ?? '').trim() };
        }
        else {
            const input = await quickInput.input({ prompt: pick.variablePrompt ?? 'Input' });
            if (!input || !input.trim()) {
                return;
            }
            variables = { input: input.trim() };
        }
        try {
            const frame = await oneshotRequest(renderer, progress, template, {
                instructions: variables.instructions,
                variables,
            });
            if (frame.error) {
                notif.notify({ severity: Severity.Error, message: `One-shot: ${frame.error}`, source: 'Crusor One-Shot' });
                return;
            }
            await clipboard.writeText(frame.text);
            const preview = frame.text.length > 400 ? frame.text.slice(0, 400) + '…' : frame.text;
            notif.notify({
                severity: Severity.Info,
                message: `One-shot done — copied to clipboard:\n\n${preview}`,
                source: 'Crusor One-Shot',
            });
        }
        catch (error) {
            notif.notify({ severity: Severity.Error, message: String(error.message ?? error), source: 'Crusor One-Shot' });
        }
    }
});
