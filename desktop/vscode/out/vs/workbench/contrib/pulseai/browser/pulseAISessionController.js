/*---------------------------------------------------------------------------------------------
 * Pulse as a session provider: the workbench's own Agent Sessions list, fed from Pulse's store.
 *
 * This is the whole registration -- one session type and one controller -- which is how the fork
 * builds its own manager (see `localAgentSessionsController.ts`). Everything it buys is already
 * written: sorting, sections, pin/archive/rename, the filter submenu, find, focus and a11y
 * commands, the attention dot, the needs-input pulse. Nothing here paints a pixel, so nothing
 * here can look like anyone's product but Pulse's.
 *--------------------------------------------------------------------------------------------*/
import { Disposable } from '../../../../base/common/lifecycle.js';
import { Emitter } from '../../../../base/common/event.js';
import { WorkbenchPhase, registerWorkbenchContribution2 } from '../../../common/contributions.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { ChatSessionStatus, IChatSessionsService, } from '../../chat/common/chatSessionsService.js';
import { isPulseSessionUri, PULSE_CHAT_SESSION_TYPE, pulseSessionRows } from '../common/pulseAISessionProjection.js';
import { IPulseAISessionStore } from '../common/pulseAISessionStore.js';
import { PulseAICommandId } from '../common/pulseAI.js';
import { sessionOpenerRegistry } from '../../chat/browser/agentSessions/agentSessionsOpener.js';
function toChatSessionStatus(statusName) {
    switch (statusName) {
        case 'inProgress': return ChatSessionStatus.InProgress;
        case 'needsInput': return ChatSessionStatus.NeedsInput;
        case 'failed': return ChatSessionStatus.Failed;
        case 'completed': return ChatSessionStatus.Completed;
        default: return undefined;
    }
}
export class PulseAISessionController extends Disposable {
    static { this.ID = 'workbench.contrib.pulseAISessionController'; }
    constructor(sessionStore, chatSessionsService) {
        super();
        this.sessionStore = sessionStore;
        this.chatSessionsService = chatSessionsService;
        this.chatSessionType = PULSE_CHAT_SESSION_TYPE;
        this._onDidChangeChatSessionItems = this._register(new Emitter());
        this.onDidChangeChatSessionItems = this._onDidChangeChatSessionItems.event;
        // One line of registration, exactly where upstream's local controller registers itself
        // (localAgentSessionsController.ts:45). It returns an IDisposable, so unloading Pulse
        // removes the rows instead of leaving a hollow session type behind.
        this._register(this.chatSessionsService.registerChatSessionItemController(this.chatSessionType, this));
        this._register(this.sessionStore.onDidChange(() => {
            this._onDidChangeChatSessionItems.fire({ addedOrUpdated: this.items });
        }));
    }
    get items() {
        return pulseSessionRows(this.sessionStore.records(), undefined, Date.now(), this.readState())
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
     * Pulse pushes frames over its stdio bridge, so there is nothing to pull. The event above is
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
}
/**
 * One opener for both surfaces. `openSessionByResource()` asks registered participants first and
 * only falls through to the chat editor path, so a click on a Pulse row inside the workbench's
 * list lands on the Pulse Manager instead of asking a chat provider to resolve a resource it does
 * not own (which is what would otherwise surface as an error toast).
 */
export class PulseAISessionOpener extends Disposable {
    static { this.ID = 'workbench.contrib.pulseAISessionOpener'; }
    constructor() {
        super();
        this._register(sessionOpenerRegistry.registerParticipant(this));
    }
    async handleOpenSession(accessor, session, openOptions) {
        return this.handleOpenSessionResource(accessor, session.resource, openOptions);
    }
    async handleOpenSessionResource(accessor, resource, _openOptions) {
        if (!isPulseSessionUri(resource)) {
            return false;
        }
        // The same command the Agent pane's Manager button runs: two entrances, one path.
        await accessor.get(ICommandService).executeCommand(PulseAICommandId.OpenManager);
        return true;
    }
}
registerWorkbenchContribution2(PulseAISessionController.ID, PulseAISessionController, WorkbenchPhase.AfterRestored);
registerWorkbenchContribution2(PulseAISessionOpener.ID, PulseAISessionOpener, WorkbenchPhase.AfterRestored);
