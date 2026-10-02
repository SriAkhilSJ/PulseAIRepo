/*---------------------------------------------------------------------------------------------
 * Crusor as a session provider: the workbench's own Agent Sessions list, fed from Crusor's store.
 *
 * This is the whole registration -- one session type and one controller -- which is how the fork
 * builds its own manager (see `localAgentSessionsController.ts`). Everything it buys is already
 * written: sorting, sections, pin/archive/rename, the filter submenu, find, focus and a11y
 * commands, the attention dot, the needs-input crusor. Nothing here paints a pixel, so nothing
 * here can look like anyone's product but Crusor's.
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
import { Disposable } from '../../../../base/common/lifecycle.js';
import { Emitter } from '../../../../base/common/event.js';
import { registerWorkbenchContribution2 } from '../../../common/contributions.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IChatSessionsService, } from '../../chat/common/chatSessionsService.js';
import { CRUSOR_CHAT_SESSION_TYPE, crusorSessionIdFromUri, crusorSessionRows } from '../common/crusorAISessionProjection.js';
import { ICrusorAISessionStore } from '../common/crusorAISessionStore.js';
import { ICrusorAIRendererService } from '../common/crusorAIRendererService.js';
import { sessionOpenerRegistry } from '../../chat/browser/agentSessions/agentSessionsOpener.js';
function toChatSessionStatus(statusName) {
    switch (statusName) {
        case 'inProgress': return 2 /* ChatSessionStatus.InProgress */;
        case 'needsInput': return 3 /* ChatSessionStatus.NeedsInput */;
        case 'failed': return 0 /* ChatSessionStatus.Failed */;
        case 'completed': return 1 /* ChatSessionStatus.Completed */;
        default: return undefined;
    }
}
let CrusorAISessionController = class CrusorAISessionController extends Disposable {
    static { this.ID = 'workbench.contrib.crusorAISessionController'; }
    constructor(sessionStore, chatSessionsService) {
        super();
        this.sessionStore = sessionStore;
        this.chatSessionsService = chatSessionsService;
        this.chatSessionType = CRUSOR_CHAT_SESSION_TYPE;
        this._onDidChangeChatSessionItems = this._register(new Emitter());
        this.onDidChangeChatSessionItems = this._onDidChangeChatSessionItems.event;
        // One line of registration, exactly where upstream's local controller registers itself
        // (localAgentSessionsController.ts:45). It returns an IDisposable, so unloading Crusor
        // removes the rows instead of leaving a hollow session type behind.
        this._register(this.chatSessionsService.registerChatSessionItemController(this.chatSessionType, this));
        this._register(this.sessionStore.onDidChange(() => {
            this._onDidChangeChatSessionItems.fire({ addedOrUpdated: this.items });
        }));
    }
    get items() {
        return crusorSessionRows(this.sessionStore.records(), undefined, Date.now(), this.readState())
            .map(row => ({
            resource: row.resource,
            label: row.label,
            description: row.description,
            status: toChatSessionStatus(row.statusName),
            timing: row.timing,
            // `changes` is passed through only when the engine reported diffs.
            ...(row.changes ? { changes: row.changes } : {}),
            ...(row.archived !== undefined ? { archived: row.archived } : {}),
        }));
    }
    /**
     * Crusor pushes frames over its stdio bridge, so there is nothing to pull. The event above is
     * the only source of truth; a refresh is a no-op rather than a fake re-query.
     */
    async refresh(token) {
        // Intentionally empty: see the comment above.
        void token;
    }
    /**
     * `setChatSessionItemRead` is deliberately NOT implemented. Implementing it declares that the
     * controller owns read state, and an in-memory map would lose it on reload; leaving it
     * undefined keeps the host's persisted per-resource tracking, which is strictly better.
     */
    readState() {
        const ids = new Set();
        for (const facts of this.sessionStore.records()) {
            ids.add(facts.sessionId);
        }
        let found = false;
        const map = new Map();
        for (const id of ids) {
            const isRead = this.sessionStore.isRead(id);
            if (isRead !== undefined) {
                map.set(id, isRead);
                found = true;
            }
        }
        return found ? map : undefined;
    }
};
CrusorAISessionController = __decorate([
    __param(0, ICrusorAISessionStore),
    __param(1, IChatSessionsService)
], CrusorAISessionController);
export { CrusorAISessionController };
/**
 * One opener for both surfaces. `openSessionByResource()` asks registered participants first and
 * only falls through to the chat editor path, so a click on a Crusor row inside the workbench's
 * list rebinds the Agent surface to that session instead of asking a chat provider to resolve a
 * resource it does not own (which is what would otherwise surface as an error toast).
 */
export class CrusorAISessionOpener extends Disposable {
    static { this.ID = 'workbench.contrib.crusorAISessionOpener'; }
    constructor() {
        super();
        this._register(sessionOpenerRegistry.registerParticipant(this));
    }
    async handleOpenSession(accessor, session, openOptions) {
        return this.handleOpenSessionResource(accessor, session.resource, openOptions);
    }
    async handleOpenSessionResource(accessor, resource, _openOptions) {
        const sessionId = crusorSessionIdFromUri(resource);
        if (!sessionId) {
            return false;
        }
        // A click on a Crusor row rebinds the Agent surface to that session (its transcript
        // hydrates from the checkpoints) instead of only revealing the Manager list.
        // ServicesAccessor is single-shot: capture before the first await (see NewSession).
        const commandService = accessor.get(ICommandService);
        const rendererService = accessor.get(ICrusorAIRendererService);
        await commandService.executeCommand("crusorai.focus" /* CrusorAICommandId.Focus */);
        rendererService.openSession(sessionId);
        return true;
    }
}
registerWorkbenchContribution2(CrusorAISessionController.ID, CrusorAISessionController, 3 /* WorkbenchPhase.AfterRestored */);
registerWorkbenchContribution2(CrusorAISessionOpener.ID, CrusorAISessionOpener, 3 /* WorkbenchPhase.AfterRestored */);
