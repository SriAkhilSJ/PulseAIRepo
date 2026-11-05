/*---------------------------------------------------------------------------------------------
 * CrusorAI Next Edit Suggestions (NES) — predicts and previews subsequent structured edits.
 * Distinct from inline ghost-text completion: reviewable, previewable via diff, safe.
 *--------------------------------------------------------------------------------------------*/

import { Emitter, Event } from '../../../../base/common/event.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import { ILogService } from '../../../../platform/log/common/log.js';
import { ICrusorAIEngineService } from '../common/crusorAIEngineService.js';
import { ICrusorAIWorkbenchService } from '../common/crusorAIWorkbenchService.js';
import type { CrusorServerEvent } from '../common/crusorAIProtocol.js';

export const ICrusorAINextEditProvider = createDecorator<CrusorAINextEditProvider>('crusorAINextEditProvider');

export interface CrusorAINextEdit {
	readonly id: string;
	readonly resource: string;
	readonly line: number;
	readonly column: number;
	readonly endLine: number;
	readonly endColumn: number;
	readonly title: string;
	readonly description: string;
	readonly confidence: number;
	readonly category: string;
	readonly oldText: string;
	readonly newText: string;
	readonly expectedVersionId?: number;
	state: 'pending' | 'previewing' | 'accepted' | 'rejected' | 'stale';
}

export class CrusorAINextEditProvider extends Disposable {
	declare readonly _serviceBrand: undefined;

	private readonly edits = new Map<string, CrusorAINextEdit>();
	private requestCounter = 0;
	private enabled = true;

	private readonly _onDidChangeEdits = this._register(new Emitter<readonly CrusorAINextEdit[]>());
	readonly onDidChangeEdits: Event<readonly CrusorAINextEdit[]> = this._onDidChangeEdits.event;

	constructor(
		@ICrusorAIEngineService private readonly engineService: ICrusorAIEngineService,
		@ICrusorAIWorkbenchService private readonly workbenchService: ICrusorAIWorkbenchService,
		@ILogService private readonly logService: ILogService,
	) {
		super();
		this._register(this.engineService.onDidReceiveFrame(frame => this.handleFrame(frame)));
	}

	requestNextEdits(resource: string, workspace: string): void {
		if (!this.enabled || !workspace?.trim()) { return; }

		const requestId = `nes-${++this.requestCounter}-${Date.now()}`;
		try {
			this.engineService.send({
				type: 'next_edit_suggestions',
				request_id: requestId,
				resource,
				workspace,
				max_suggestions: 5,
			} as any);
		} catch (err) {
			this.logService.warn('[CrusorAI NextEdit] failed to request next edits', err);
		}
	}

	getPendingEdits(resource?: string): readonly CrusorAINextEdit[] {
		const list = [...this.edits.values()].filter(e => e.state === 'pending' || e.state === 'previewing');
		if (resource) {
			return list.filter(e => e.resource === resource);
		}
		return list;
	}

	async previewEdit(editId: string): Promise<boolean> {
		const edit = this.edits.get(editId);
		if (!edit || edit.state === 'accepted' || edit.state === 'rejected') {
			return false;
		}

		edit.state = 'previewing';
		this._onDidChangeEdits.fire(this.getPendingEdits());

		try {
			await this.workbenchService.openInlineDiff({
				toolId: edit.id,
				label: edit.title || 'Crusor Next Edit',
				resource: edit.resource,
				original: edit.oldText,
				modified: edit.newText,
			});
			return true;
		} catch (err) {
			this.logService.error('[CrusorAI NextEdit] failed to open inline preview', err);
			return false;
		}
	}

	async acceptEdit(editId: string): Promise<boolean> {
		const edit = this.edits.get(editId);
		if (!edit || edit.state === 'accepted' || edit.state === 'rejected') {
			return false;
		}

		if (!this.workbenchService.isWorkspaceTrusted()) {
			throw new Error('Crusor NextEdit cannot apply edits before workspace trust is granted');
		}

		try {
			const outcome = await this.workbenchService.applyWorkspaceEdit({
				label: edit.title || 'Crusor Next Edit',
				approvalToolId: edit.id,
				showPreview: false,
				edits: [
					{
						resource: edit.resource,
						range: {
							startLine: edit.line,
							startColumn: edit.column,
							endLine: edit.endLine,
							endColumn: edit.endColumn,
						},
						text: edit.newText,
						expectedVersionId: edit.expectedVersionId,
					},
				],
			});

			if (outcome.applied) {
				edit.state = 'accepted';
				this.edits.delete(editId);
				this._onDidChangeEdits.fire(this.getPendingEdits());
				return true;
			}
			return false;
		} catch (err) {
			this.logService.error('[CrusorAI NextEdit] failed to accept and apply edit', err);
			return false;
		}
	}

	rejectEdit(editId: string): void {
		const edit = this.edits.get(editId);
		if (edit) {
			edit.state = 'rejected';
			this.edits.delete(editId);
			this._onDidChangeEdits.fire(this.getPendingEdits());
		}
	}

	clearSuggestions(resource?: string): void {
		if (resource) {
			for (const [id, edit] of this.edits.entries()) {
				if (edit.resource === resource) {
					this.edits.delete(id);
				}
			}
		} else {
			this.edits.clear();
		}
		this._onDidChangeEdits.fire(this.getPendingEdits());
	}

	invalidateStale(resource: string, currentVersionId: number): void {
		for (const [id, edit] of this.edits.entries()) {
			if (edit.resource === resource && edit.expectedVersionId !== undefined && edit.expectedVersionId !== currentVersionId) {
				edit.state = 'stale';
				this.edits.delete(id);
			}
		}
		this._onDidChangeEdits.fire(this.getPendingEdits());
	}

	private handleFrame(frame: CrusorServerEvent): void {
		if (frame.type !== 'next_edit_result') { return; }
		const result = frame as any;
		const suggestions = (result.suggestions ?? []) as any[];

		for (let i = 0; i < suggestions.length; i++) {
			const s = suggestions[i];
			if (!s.resource || typeof s.line !== 'number' || s.line < 1) { continue; }

			const id = s.id || `edit-${Date.now()}-${i}`;
			const edit: CrusorAINextEdit = {
				id,
				resource: s.resource,
				line: s.line,
				column: s.column ?? 1,
				endLine: s.endLine ?? s.line,
				endColumn: s.endColumn ?? s.column ?? 1,
				title: s.title || 'Suggested edit',
				description: s.description || '',
				confidence: typeof s.confidence === 'number' ? s.confidence : 1.0,
				category: s.category || 'refactor',
				oldText: s.oldText ?? '',
				newText: s.newText ?? '',
				expectedVersionId: s.expectedVersionId,
				state: 'pending',
			};
			this.edits.set(id, edit);
		}

		this._onDidChangeEdits.fire(this.getPendingEdits());
	}

	override dispose(): void {
		this.edits.clear();
		super.dispose();
	}
}
