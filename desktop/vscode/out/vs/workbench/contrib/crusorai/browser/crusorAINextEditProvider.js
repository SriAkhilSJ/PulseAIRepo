/*---------------------------------------------------------------------------------------------
 * CrusorAI Next Edit Suggestions (NES) — predicts and previews subsequent structured edits.
 * Distinct from inline ghost-text completion: reviewable, previewable via diff, safe.
 *--------------------------------------------------------------------------------------------*/
var __decorate = (this && this.__decorate) || function (decorators, target, key, desc) {
    var c = arguments.length, r = c < 3 ? target : desc === null ? desc = Object.getOwnPropertyDescriptor(target, key) : desc, d;
    if (typeof Reflect === "object" && typeof Reflect.decorate === "function") r = Reflect.decorate(decorators, target, key, desc);
    else for (var i = decorators.length - 1; i >= 0; i--) if (d = decorators[i]) r = (c < 3 ? d(r) : c > 3 ? d(target, key, r) : d(target, key)) || r;
    return c > 3 && r && Object.defineProperty(target, key, r), r;
};
var __param = (this && this.__param) || function (paramIndex, decorator) {
    return function (target, key) { decorator(target, key, paramIndex); }
};
import { Emitter } from '../../../../base/common/event.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import { ILogService } from '../../../../platform/log/common/log.js';
import { ICrusorAIEngineService } from '../common/crusorAIEngineService.js';
import { ICrusorAIWorkbenchService } from '../common/crusorAIWorkbenchService.js';
export const ICrusorAINextEditProvider = createDecorator('crusorAINextEditProvider');
let CrusorAINextEditProvider = class CrusorAINextEditProvider extends Disposable {
    constructor(engineService, workbenchService, logService) {
        super();
        this.engineService = engineService;
        this.workbenchService = workbenchService;
        this.logService = logService;
        this.edits = new Map();
        this.requestCounter = 0;
        this.enabled = true;
        this._onDidChangeEdits = this._register(new Emitter());
        this.onDidChangeEdits = this._onDidChangeEdits.event;
        this._register(this.engineService.onDidReceiveFrame(frame => this.handleFrame(frame)));
    }
    requestNextEdits(resource, workspace) {
        if (!this.enabled || !workspace?.trim()) {
            return;
        }
        const requestId = `nes-${++this.requestCounter}-${Date.now()}`;
        try {
            this.engineService.send({
                type: 'next_edit_suggestions',
                request_id: requestId,
                resource,
                workspace,
                max_suggestions: 5,
            });
        }
        catch (err) {
            this.logService.warn('[CrusorAI NextEdit] failed to request next edits', err);
        }
    }
    getPendingEdits(resource) {
        const list = [...this.edits.values()].filter(e => e.state === 'pending' || e.state === 'previewing');
        if (resource) {
            return list.filter(e => e.resource === resource);
        }
        return list;
    }
    async previewEdit(editId) {
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
        }
        catch (err) {
            this.logService.error('[CrusorAI NextEdit] failed to open inline preview', err);
            return false;
        }
    }
    async acceptEdit(editId) {
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
        }
        catch (err) {
            this.logService.error('[CrusorAI NextEdit] failed to accept and apply edit', err);
            return false;
        }
    }
    rejectEdit(editId) {
        const edit = this.edits.get(editId);
        if (edit) {
            edit.state = 'rejected';
            this.edits.delete(editId);
            this._onDidChangeEdits.fire(this.getPendingEdits());
        }
    }
    clearSuggestions(resource) {
        if (resource) {
            for (const [id, edit] of this.edits.entries()) {
                if (edit.resource === resource) {
                    this.edits.delete(id);
                }
            }
        }
        else {
            this.edits.clear();
        }
        this._onDidChangeEdits.fire(this.getPendingEdits());
    }
    invalidateStale(resource, currentVersionId) {
        for (const [id, edit] of this.edits.entries()) {
            if (edit.resource === resource && edit.expectedVersionId !== undefined && edit.expectedVersionId !== currentVersionId) {
                edit.state = 'stale';
                this.edits.delete(id);
            }
        }
        this._onDidChangeEdits.fire(this.getPendingEdits());
    }
    handleFrame(frame) {
        if (frame.type !== 'next_edit_result') {
            return;
        }
        const result = frame;
        const suggestions = (result.suggestions ?? []);
        for (let i = 0; i < suggestions.length; i++) {
            const s = suggestions[i];
            if (!s.resource || typeof s.line !== 'number' || s.line < 1) {
                continue;
            }
            const id = s.id || `edit-${Date.now()}-${i}`;
            const edit = {
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
    dispose() {
        this.edits.clear();
        super.dispose();
    }
};
CrusorAINextEditProvider = __decorate([
    __param(0, ICrusorAIEngineService),
    __param(1, ICrusorAIWorkbenchService),
    __param(2, ILogService)
], CrusorAINextEditProvider);
export { CrusorAINextEditProvider };
