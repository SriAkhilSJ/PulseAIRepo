/*---------------------------------------------------------------------------------------------
 *  Copyright (c) PulseCode AI. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, append } from '../../../../base/browser/dom.js';
import { renderMarkdown, type MarkdownRenderOptions } from '../../../../base/browser/markdownRenderer.js';
import { MarkdownString } from '../../../../base/common/htmlContent.js';
import { CancellationTokenSource } from '../../../../base/common/cancellation.js';
import { localize } from '../../../../nls.js';
import { IContextKeyService } from '../../../../platform/contextkey/common/contextkey.js';
import { IContextMenuService } from '../../../../platform/contextview/browser/contextView.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IKeybindingService } from '../../../../platform/keybinding/common/keybinding.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IViewPaneOptions, ViewPane } from '../../../browser/parts/views/viewPane.js';
import { IViewDescriptorService } from '../../../common/views.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { PulseAgentModelService } from '../common/pulseAgentModelService.js';
import { readPulseConfig } from '../common/pulseAgentConfig.js';
import type { PulseModelProvider, IPulseChatMessage } from '../common/pulseAgentTypes.js';
export const PulseAgentViewId = 'workbench.view.pulseAgent';

/**
 * PulseAgentView — a native ViewPane rendered inside the Secondary (Auxiliary) Side Bar.
 *
 * Layout:
 * ┌──────────────────────────┐
 * │  ♥ PulseCode AI Agent    │  ← header with heartbeat indicator
 * ├──────────────────────────┤
 * │                          │
 * │  Thinking... 9s          │  ← scrollable log area
 * │  ▸ Reading file.ts       │
 * │  ▸ Analyzing imports     │
 * │  ...                     │
 * │                          │
 * ├──────────────────────────┤
 * │  [Ask Pulse anything...] │  ← fixed footer: chat input box
 * └──────────────────────────┘
 */
export class PulseAgentView extends ViewPane {

	private bodyElement: HTMLElement | undefined;
	private headerElement: HTMLElement | undefined;
	private heartbeatIndicator: HTMLElement | undefined;
	private logArea: HTMLElement | undefined;
	private footerElement: HTMLElement | undefined;
	private inputElement: HTMLInputElement | undefined;
	private statusDot: HTMLElement | undefined;
	private statusText: HTMLElement | undefined;
	private currentCts: CancellationTokenSource | undefined;

	private elapsedTimer: ReturnType<typeof setInterval> | undefined;
	private elapsedSeconds: number = 0;

	private readonly modelService: PulseAgentModelService;

	constructor(
		options: IViewPaneOptions,
		@IKeybindingService keybindingService: IKeybindingService,
		@IContextMenuService contextMenuService: IContextMenuService,
		@IConfigurationService configurationService: IConfigurationService,
		@IContextKeyService contextKeyService: IContextKeyService,
		@IViewDescriptorService viewDescriptorService: IViewDescriptorService,
		@IInstantiationService instantiationService: IInstantiationService,
		@IOpenerService openerService: IOpenerService,
		@IThemeService themeService: IThemeService,
		@IHoverService hoverService: IHoverService,
		@IEditorService private readonly editorService: IEditorService,
	) {
		super(options, keybindingService, contextMenuService, configurationService, contextKeyService, viewDescriptorService, instantiationService, openerService, themeService, hoverService);
		this.modelService = instantiationService.createInstance(PulseAgentModelService);
	}

	// ─── View lifecycle ────────────────────────────────────────────────

	protected override renderBody(container: HTMLElement): void {
		super.renderBody(container);

		this.bodyElement = append(container, $('.pulse-agent-body'));

		// ── Header: heartbeat bar ──
		this.headerElement = append(this.bodyElement, $('.pulse-agent-header'));

		// Red top border line — the "heartbeat" visual
		this.heartbeatIndicator = append(this.headerElement, $('.pulse-agent-heartbeat'));
		this.heartbeatIndicator.style.background = 'linear-gradient(90deg, #e74c3c, #ff6b6b, #e74c3c)';
		this.heartbeatIndicator.style.height = '2px';
		this.heartbeatIndicator.style.width = '100%';
		this.heartbeatIndicator.style.borderRadius = '1px';

		// Header label
		const labelContainer = append(this.headerElement, $('.pulse-agent-header-label'));
		labelContainer.style.display = 'flex';
		labelContainer.style.alignItems = 'center';
		labelContainer.style.gap = '6px';
		labelContainer.style.padding = '8px 12px 6px';

		const pulseIcon = append(labelContainer, $('span'));
		pulseIcon.textContent = '♥';
		pulseIcon.style.color = '#e74c3c';
		pulseIcon.style.fontSize = '14px';
		pulseIcon.style.fontWeight = 'bold';

		const titleText = append(labelContainer, $('span'));
		titleText.textContent = localize('pulseAgent.title', 'PulseCode AI Agent');
		titleText.style.color = '#cccccc';
		titleText.style.fontSize = '12px';
		titleText.style.fontWeight = '600';
		titleText.style.letterSpacing = '0.5px';
		titleText.style.textTransform = 'uppercase';

		// Status indicator
		this.statusDot = append(labelContainer, $('span'));
		const statusDot = this.statusDot;
		statusDot.style.width = '6px';
		statusDot.style.height = '6px';
		statusDot.style.borderRadius = '50%';
		statusDot.style.background = '#4caf50';
		statusDot.style.marginLeft = 'auto';

		this.statusText = append(labelContainer, $('span'));
		this.statusText.textContent = localize('pulseAgent.status.ready', 'Ready');
		this.statusText.style.color = '#4caf50';
		this.statusText.style.fontSize = '11px';

		// ── Thinking / Log Area (scrollable) ──
		const logContainer = append(this.bodyElement, $('.pulse-agent-log-container'));
		logContainer.style.flex = '1';
		logContainer.style.overflow = 'hidden';
		logContainer.style.position = 'relative';

		this.logArea = append(logContainer, $('.pulse-agent-log'));
		this.logArea.style.padding = '8px 12px';
		this.logArea.style.fontSize = '12px';
		this.logArea.style.fontFamily = 'var(--vscode-editor-font-family)';
		this.logArea.style.lineHeight = '1.6';
		this.logArea.style.overflowY = 'auto';
		this.logArea.style.height = '100%';
		this.logArea.style.color = '#cccccc';

		// Welcome message
		this._addLogEntry('Ask Pulse anything about your code.', '#9e9e9e');

		// ── Footer: Chat Input ──
		this.footerElement = append(this.bodyElement, $('.pulse-agent-footer'));
		this.footerElement.style.borderTop = '1px solid #333333';
		this.footerElement.style.padding = '8px';

		this.inputElement = document.createElement('input') as HTMLInputElement;
		this.inputElement.type = 'text';
		this.inputElement.placeholder = localize('pulseAgent.input.placeholder', 'Ask Pulse anything...');
		this.inputElement.style.width = '100%';
		this.inputElement.style.padding = '8px 12px';
		this.inputElement.style.background = '#2d2d2d';
		this.inputElement.style.border = '1px solid #3c3c3c';
		this.inputElement.style.borderRadius = '6px';
		this.inputElement.style.color = '#cccccc';
		this.inputElement.style.fontSize = '13px';
		this.inputElement.style.outline = 'none';
		this.inputElement.style.boxSizing = 'border-box';
		this.inputElement.style.fontFamily = 'var(--vscode-editor-font-family)';

		// Focus glow
		this.inputElement.addEventListener('focus', () => {
			if (this.inputElement) {
				this.inputElement.style.borderColor = '#7c4dff';
				this.inputElement.style.boxShadow = '0 0 0 1px rgba(124, 77, 255, 0.3)';
			}
		});
		this.inputElement.addEventListener('blur', () => {
			if (this.inputElement) {
				this.inputElement.style.borderColor = '#3c3c3c';
				this.inputElement.style.boxShadow = 'none';
			}
		});

		// Submit on Enter
		this.inputElement.addEventListener('keydown', (e: KeyboardEvent) => {
			if (e.key === 'Enter' && this.inputElement?.value.trim()) {
				this._onSubmit(this.inputElement.value.trim());
				this.inputElement.value = '';
			}
		});

		this.footerElement.appendChild(this.inputElement);

		// ── Styles ──
		this.bodyElement.style.display = 'flex';
		this.bodyElement.style.flexDirection = 'column';
		this.bodyElement.style.height = '100%';
		this.bodyElement.style.background = '#1e1e1e';
	}

	protected override layoutBody(height: number, width: number): void {
		super.layoutBody(height, width);
	}

	// ─── Public API ────────────────────────────────────────────────────

	/**
	 * Add a log entry to the thinking area.
	 * @param text  The log message
	 * @param color Optional text color
	 */
	addLogEntry(text: string, color?: string): void {
		this._addLogEntry(text, color);
	}

	/**
	 * Clear all log entries.
	 */
	clearLogs(): void {
		if (this.logArea) {
			this.logArea.innerHTML = '';
		}
	}

	/**
	 * Start a thinking timer (shows "Thinking... Xs").
	 */
	startThinking(): void {
		this.elapsedSeconds = 0;

		if (this.logArea) {
			// Remove previous "Thinking..." entry if present
			const firstChild = this.logArea.firstElementChild;
			if (firstChild && firstChild.textContent?.startsWith('Thinking...')) {
				this.logArea.removeChild(firstChild);
			}
		}

		// Add the timed "Thinking... Xs" entry
		this._addLogEntry(`Thinking... ${this.elapsedSeconds}s`, '#9e9e9e');

		this.elapsedTimer = setInterval(() => {
			this.elapsedSeconds++;
			if (this.logArea) {
				const firstChild = this.logArea.firstElementChild;
				if (firstChild && firstChild.textContent?.startsWith('Thinking...')) {
					firstChild.textContent = `Thinking... ${this.elapsedSeconds}s`;
				}
			}
		}, 1000);
	}

	/**
	 * Stop the thinking timer.
	 */
	stopThinking(): void {
		if (this.elapsedTimer) {
			clearInterval(this.elapsedTimer);
			this.elapsedTimer = undefined;
		}
		// Remove the "Thinking... Xs" entry
		if (this.logArea) {
			const firstChild = this.logArea.firstElementChild;
			if (firstChild && firstChild.textContent?.startsWith('Thinking...')) {
				this.logArea.removeChild(firstChild);
			}
		}
	}

	// ─── Private ───────────────────────────────────────────────────────

	private _addLogEntry(text: string, color?: string): void {
		if (!this.logArea) {
			return;
		}
		const entry = append(this.logArea, $('div'));
		entry.textContent = text;
		entry.style.padding = '2px 0';
		entry.style.whiteSpace = 'pre-wrap';
		entry.style.wordBreak = 'break-word';
		if (color) {
			entry.style.color = color;
		}
		this.logArea.scrollTop = this.logArea.scrollHeight;
	}


	/**
	 * Render the final AI reply using VS Code's native markdown renderer,
	 * which parses code blocks, applies syntax highlighting via the
	 * language service, and adds "Apply to Editor" buttons.
	 */
	private _renderReply(text: string): void {
		if (!this.logArea) {
			return;
		}

		const entry = append(this.logArea, $('div'));
		entry.style.padding = '8px 12px';
		entry.style.margin = '8px 0';
		entry.style.backgroundColor = '#252526';
		entry.style.borderLeft = '3px solid #e74c3c';
		entry.style.borderRadius = '0 4px 4px 0';
		entry.style.color = '#e0e0e0';
		entry.style.wordBreak = 'break-word';

		// Use renderMarkdown with a codeBlockRendererSync that creates
		// a styled code block header + <pre><code> + "Apply to Editor" button.
		const renderOptions: MarkdownRenderOptions = {
			codeBlockRendererSync: (languageId: string, code: string, raw?: string) => {
				return this._createCodeBlockElement(languageId, code);
			}
		};

		const md = new MarkdownString(text, { isTrusted: true });
		const result = renderMarkdown(md, renderOptions);

		entry.appendChild(result.element);

		this.logArea.scrollTop = this.logArea.scrollHeight;
	}

	/**
	 * Create a styled code block element with language label and
	 * "Apply to Editor" button.
	 */
	private _createCodeBlockElement(languageId: string, code: string): HTMLElement {
		const codeContainer = document.createElement('div');
		codeContainer.style.backgroundColor = '#1e1e1e';
		codeContainer.style.border = '1px solid #3c3c3c';
		codeContainer.style.borderRadius = '4px';
		codeContainer.style.marginTop = '8px';
		codeContainer.style.marginBottom = '8px';
		codeContainer.style.overflow = 'hidden';

		// ── Header bar: language label + apply button ──
		const codeHeader = document.createElement('div');
		codeHeader.style.display = 'flex';
		codeHeader.style.justifyContent = 'space-between';
		codeHeader.style.alignItems = 'center';
		codeHeader.style.backgroundColor = '#2d2d2d';
		codeHeader.style.padding = '4px 8px';
		codeHeader.style.fontSize = '11px';
		codeHeader.style.color = '#cccccc';

		const langSpan = document.createElement('span');
		langSpan.textContent = languageId || 'code';
		langSpan.style.fontFamily = 'var(--vscode-editor-font-family)';

		const applyBtn = document.createElement('button');
		applyBtn.textContent = 'Apply to Editor';
		applyBtn.style.backgroundColor = '#e74c3c';
		applyBtn.style.color = 'white';
		applyBtn.style.border = 'none';
		applyBtn.style.borderRadius = '3px';
		applyBtn.style.padding = '2px 8px';
		applyBtn.style.cursor = 'pointer';
		applyBtn.style.fontSize = '10px';
		applyBtn.style.fontFamily = 'var(--vscode-editor-font-family)';
		applyBtn.style.lineHeight = '18px';

		applyBtn.onclick = () => {
			this.applyCodeToEditor(code);
			applyBtn.textContent = 'Applied!';
			applyBtn.style.backgroundColor = '#4caf50';
			setTimeout(() => {
				applyBtn.textContent = 'Apply to Editor';
				applyBtn.style.backgroundColor = '#e74c3c';
			}, 2000);
		};

		codeHeader.appendChild(langSpan);
		codeHeader.appendChild(applyBtn);

		// ── Code body ──
		const codePre = document.createElement('pre');
		codePre.style.margin = '0';
		codePre.style.padding = '8px';
		codePre.style.overflowX = 'auto';
		codePre.style.backgroundColor = '#1e1e1e';

		const codeCode = document.createElement('code');
		codeCode.textContent = code;
		codeCode.style.fontFamily = 'var(--vscode-editor-font-family)';
		codeCode.style.fontSize = '12px';
		codeCode.style.whiteSpace = 'pre-wrap';
		codeCode.style.wordBreak = 'break-word';

		codePre.appendChild(codeCode);
		codeContainer.appendChild(codeHeader);
		codeContainer.appendChild(codePre);

		return codeContainer;
	}

	/**
	 * Grab the text content and filename of the currently active editor.
	 */
	private getActiveEditorContext(): { filename: string; text: string } | null {
		const activeTextEditorControl = this.editorService.activeTextEditorControl;
		if (!activeTextEditorControl) {
			return null;
		}

		const editorModel = (activeTextEditorControl as any).getModel();
		if (editorModel && typeof (editorModel as any).getValue === 'function') {
			const text = (editorModel as any).getValue();
			const uri = (editorModel as any).uri;
			const filename = uri ? uri.path.split('/').pop() : 'unknown';
			return { filename, text };
		}
		return null;
	}

	/**
	 * Insert code into the currently active editor at the cursor position.
	 */
	private applyCodeToEditor(code: string): void {
		const activeTextEditorControl = this.editorService.activeTextEditorControl;
		if (!activeTextEditorControl) {
			this._addLogEntry('[error] No active text editor found', '#e74c3c');
			return;
		}

		const editor = activeTextEditorControl as any;
		if (typeof editor.executeEdits === 'function' && typeof editor.getPosition === 'function') {
			const position = editor.getPosition();
			editor.executeEdits('pulseAgent', [{
				range: {
					startLineNumber: position.lineNumber,
					startColumn: position.column,
					endLineNumber: position.lineNumber,
					endColumn: position.column
				},
				text: code,
				forceMoveMarkers: true
			}]);
			editor.focus();
		} else {
			this._addLogEntry('[error] Editor does not support executeEdits', '#e74c3c');
		}
	}

	private async _onSubmit(text: string): Promise<void> {
		if (!this.inputElement) {
			return;
		}

		// Cancel any in-flight request
		if (this.currentCts) {
			this.currentCts.cancel();
			this.currentCts.dispose();
			this.currentCts = undefined;
			this.stopThinking();
		}

		// Show the user's message in the log
		this._addLogEntry(`[user] ${text}`, '#80cbc4');

		// Read config
		const config = readPulseConfig(this.configurationService);
		const providerKey = config.defaultProvider || 'google';
		const provider = config.providers[providerKey as keyof typeof config.providers];
		if (!provider || !provider.apiKey) {
			this._addLogEntry(`[error] No API key configured for "${providerKey}". Set via settings or environment variable.`, '#e74c3c');
			return;
		}

		// Build messages
		const context = this.getActiveEditorContext();
		const systemPrompt = context
			? `You are PulseCode AI, an expert coding assistant integrated into VS Code. The user has a file named '${context.filename}' open with the following content:\n\n${context.text}\n\nAnswer the user's question about their code concisely and accurately.`
			: 'You are PulseCode AI, an expert coding assistant integrated into VS Code. Answer the user\'s coding questions concisely and accurately.';

		const messages: IPulseChatMessage[] = [
			{ role: 'system', content: systemPrompt },
			{ role: 'user', content: text },
		];

		// Start streaming
		this.currentCts = new CancellationTokenSource();
		const token = this.currentCts.token;

		this.startThinking();

		let replyText = '';
		let hasError = false;

		try {
			for await (const delta of this.modelService.streamRequest(
				providerKey as PulseModelProvider,
				provider.model ?? '',
				provider.apiKey,
				provider.baseUrl ?? '',
				messages,
				undefined, // no tools yet
				token,
				2048, // maxTokens
				0.7, // temperature
			)) {
				if (token.isCancellationRequested) {
					return;
				}

				switch (delta.type) {
					case 'text':
						replyText += delta.text ?? '';
						break;
					case 'tool_call_start':
						// Tools not yet implemented — log silently
						break;
					case 'tool_call_arg':
						break;
					case 'done':
						break;
					case 'error':
						this.stopThinking();
						this._addLogEntry(`[error] ${delta.error ?? 'Unknown error'}`, '#e74c3c');
						hasError = true;
						return;
				}
			}
		} catch (err: unknown) {
			this.stopThinking();
			const msg = err instanceof Error ? err.message : String(err);
			this._addLogEntry(`[error] ${msg}`, '#e74c3c');
			hasError = true;
			return;
		} finally {
			this.stopThinking();
			if (this.currentCts) {
				this.currentCts.dispose();
				this.currentCts = undefined;
			}
		}

		if (!hasError && replyText.trim()) {
			this._renderReply(replyText.trim());
		} else if (!hasError) {
			this._addLogEntry('[empty response] The model returned no content', '#ff9800');
		}
	}

	// ─── Dispose ───────────────────────────────────────────────────────

	override dispose(): void {
		if (this.currentCts) {
			this.currentCts.cancel();
			this.currentCts.dispose();
			this.currentCts = undefined;
		}
		this.stopThinking();
		super.dispose();
	}
}
