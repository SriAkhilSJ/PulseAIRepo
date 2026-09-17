/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, addDisposableListener, append, clearNode, EventType, h } from '../../../../base/browser/dom.js';
import { KeybindingLabel } from '../../../../base/browser/ui/keybindingLabel/keybindingLabel.js';
import { coalesce, shuffle } from '../../../../base/common/arrays.js';
import { Disposable, DisposableStore } from '../../../../base/common/lifecycle.js';
import { isMacintosh, isWeb, OS } from '../../../../base/common/platform.js';
import { localize } from '../../../../nls.js';
import { MenuId } from '../../../../platform/actions/common/actions.js';
import { HiddenItemStrategy, MenuWorkbenchToolBar } from '../../../../platform/actions/browser/toolbar.js';
import { CommandsRegistry, ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { ContextKeyExpr, ContextKeyExpression, IContextKeyService } from '../../../../platform/contextkey/common/contextkey.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IKeybindingService } from '../../../../platform/keybinding/common/keybinding.js';
import { IStorageService, StorageScope, StorageTarget, WillSaveStateReason } from '../../../../platform/storage/common/storage.js';
import { defaultKeybindingLabelStyles } from '../../../../platform/theme/browser/defaultStyles.js';
import { IWorkspaceContextService, WorkbenchState } from '../../../../platform/workspace/common/workspace.js';

interface WatermarkEntry {
	readonly id: string;
	readonly text: string;
	readonly description?: string;
	readonly icon?: string;
	readonly when?: {
		native?: ContextKeyExpression;
		web?: ContextKeyExpression;
	};
}

interface ActionCard {
	readonly id: string;
	readonly title: string;
	readonly description: string;
	readonly icon: string;
	readonly command: string;
}

const showChatContextKey = ContextKeyExpr.and(ContextKeyExpr.equals('chatSetupHidden', false), ContextKeyExpr.equals('chatSetupDisabledInWorkspace', false));

const openChat: WatermarkEntry = { text: localize('watermark.openChat', "Open Chat"), id: 'workbench.action.chat.open', when: { native: showChatContextKey, web: showChatContextKey } };
const showCommands: WatermarkEntry = { text: localize('watermark.showCommands', "Show All Commands"), id: 'workbench.action.showCommands' };
const gotoFile: WatermarkEntry = { text: localize('watermark.quickAccess', "Go to File"), id: 'workbench.action.quickOpen' };
const openFile: WatermarkEntry = { text: localize('watermark.openFile', "Open File"), id: 'workbench.action.files.openFile' };
const openFolder: WatermarkEntry = { text: localize('watermark.openFolder', "Open Folder"), id: 'workbench.action.files.openFolder' };
const openFileOrFolder: WatermarkEntry = { text: localize('watermark.openFileFolder', "Open File or Folder"), id: 'workbench.action.files.openFileFolder' };
const openRecent: WatermarkEntry = { text: localize('watermark.openRecent', "Open Recent"), id: 'workbench.action.openRecent' };
const newUntitledFile: WatermarkEntry = { text: localize('watermark.newUntitledFile', "New Untitled Text File"), id: 'workbench.action.files.newUntitledFile' };
const findInFiles: WatermarkEntry = { text: localize('watermark.findInFiles', "Find in Files"), id: 'workbench.action.findInFiles' };
const toggleTerminal: WatermarkEntry = { text: localize({ key: 'watermark.toggleTerminal', comment: ['toggle is a verb here'] }, "Toggle Terminal"), id: 'workbench.action.terminal.toggleTerminal', when: { web: ContextKeyExpr.equals('terminalProcessSupported', true) } };
const startDebugging: WatermarkEntry = { text: localize('watermark.startDebugging', "Start Debugging"), id: 'workbench.action.debug.start', when: { web: ContextKeyExpr.equals('terminalProcessSupported', true) } };
const openSettings: WatermarkEntry = { text: localize('watermark.openSettings', "Open Settings"), id: 'workbench.action.openSettings' };

const baseEntries: WatermarkEntry[] = [
	openChat,
	showCommands,
];

const emptyWindowEntries: WatermarkEntry[] = coalesce([
	...baseEntries,
	openRecent,
	...(isMacintosh && !isWeb ? [openFileOrFolder] : [openFile, openFolder]),
	isMacintosh && !isWeb ? newUntitledFile : undefined,
]);

const workspaceEntries: WatermarkEntry[] = [
	...baseEntries,
];

const otherEntries: WatermarkEntry[] = [
	gotoFile,
	findInFiles,
	startDebugging,
	toggleTerminal,
	openSettings,
];

const actionCards: ActionCard[] = [
	{
		id: 'openProject',
		title: localize('watermark.openProject', "Open Project"),
		description: localize('watermark.openProject.desc', "Open a folder to start working"),
		icon: 'open-project',
		command: isMacintosh ? 'workbench.action.files.openFileFolder' : 'workbench.action.files.openFolder',
	},
	{
		id: 'openFile',
		title: localize('watermark.openFileCard', "Open File"),
		description: localize('watermark.openFileCard.desc', "Open a single file"),
		icon: 'open-file',
		command: 'workbench.action.files.openFile',
	},
	{
		id: 'cloneGithub',
		title: localize('watermark.cloneGithub', "Clone from GitHub"),
		description: localize('watermark.cloneGithub.desc', "Clone a remote repository"),
		icon: 'clone-github',
		command: 'git.clone',
	},
	{
		id: 'newFile',
		title: localize('watermark.newFile', "New File"),
		description: localize('watermark.newFile.desc', "Start with a blank file"),
		icon: 'new-file',
		command: 'workbench.action.files.newUntitledFile',
	},
];

const MAX_RECENT_ITEMS = 5;

const icons: { [key: string]: string } = {
	'open-project': `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M3 7V17C3 18.1046 3.89543 19 5 19H19C20.1046 19 21 18.1046 21 17V9C21 7.89543 20.1046 7 19 7H13L11 5H5C3.89543 5 3 5.89543 3 7Z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
	'open-file': `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M14 2H6C4.89543 2 4 2.89543 4 4V20C4 21.1046 4.89543 22 6 22H18C19.1046 22 20 21.1046 20 20V8L14 2Z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M14 2V8H20" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
	'clone-github': `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M9 19C9 20.1046 8.10457 21 7 21C5.89543 21 5 20.1046 5 19C5 17.8954 5.89543 17 7 17C7.35064 17 7.68722 17.088 7.98226 17.2426L8.7426 15.4823C8.27288 15.1851 7.89965 14.7945 7.65282 14.3436L5.85439 14.8544C5.62411 14.9207 5.38096 14.9564 5.13398 14.9596L4.5 15C3.67157 15 3 14.3284 3 13.5V5.5C3 4.67157 3.67157 4 4.5 4H14.5C15.3284 4 16 4.67157 16 5.5V6M16 13H21M18 11V15" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
	'new-file': `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 5V19M5 12H19" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
	'folder': `<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M3 7V17C3 18.1046 3.89543 19 5 19H19C20.1046 19 21 18.1046 21 17V9C21 7.89543 20.1046 7 19 7H13L11 5H5C3.89543 5 3 5.89543 3 7Z" stroke="#569cd6" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
};

export class EditorGroupWatermark extends Disposable {

	private static readonly CACHED_WHEN = 'editorGroupWatermark.whenConditions';
	private static readonly SETTINGS_KEY = 'workbench.tips.enabled';
	private static readonly MINIMUM_ENTRIES = 3;

	private readonly cachedWhen: { [when: string]: boolean };

	private readonly shortcuts: HTMLElement;
	private readonly actionCardsContainer: HTMLElement;
	private readonly recentSection: HTMLElement;
	private readonly toolbarContainer: HTMLElement;
	private readonly transientDisposables = this._register(new DisposableStore());
	private readonly keybindingLabels = this._register(new DisposableStore());

	private enabled = false;
	private workbenchState: WorkbenchState;

	constructor(
		container: HTMLElement,
		@IKeybindingService private readonly keybindingService: IKeybindingService,
		@IWorkspaceContextService private readonly contextService: IWorkspaceContextService,
		@IContextKeyService private readonly contextKeyService: IContextKeyService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@IStorageService private readonly storageService: IStorageService,
		@IInstantiationService private readonly instantiationService: IInstantiationService,
		@ICommandService private readonly commandService: ICommandService
	) {
		super();

		this.cachedWhen = this.storageService.getObject(EditorGroupWatermark.CACHED_WHEN, StorageScope.PROFILE, Object.create(null));
		this.workbenchState = this.contextService.getWorkbenchState();

		const elements = h('.editor-group-watermark-wrapper', [
			h('.editor-group-watermark-toolbar-container@toolbarContainer'),
			h('.editor-group-watermark', [
				h('.watermark-container', [
					h('.letterpress'),
					h('.watermark-title@title'),
					h('.watermark-subtitle@subtitle'),
					h('.action-cards@actionCards'),
					h('.recent-section@recentSection'),
					h('.shortcuts@shortcuts'),
				])
			])
		]);

		append(container, elements.root);
		this.shortcuts = elements.shortcuts;
		this.actionCardsContainer = elements.actionCards;
		this.recentSection = elements.recentSection;
		this.toolbarContainer = elements.toolbarContainer;

		const title = elements.title;
		title.textContent = 'Crusor AI';

		const subtitle = elements.subtitle;
		subtitle.textContent = 'AI-Powered Code Intelligence';

		this._register(this.instantiationService.createInstance(MenuWorkbenchToolBar, this.toolbarContainer, MenuId.EditorGroupWatermarkToolbar, {
			hiddenItemStrategy: HiddenItemStrategy.NoHide,
			highlightToggledItems: true,
			menuOptions: { shouldForwardArgs: true }
		}));

		this.registerListeners();

		this.render();
	}

	private registerListeners(): void {
		this._register(this.configurationService.onDidChangeConfiguration(e => {
			if (
				e.affectsConfiguration(EditorGroupWatermark.SETTINGS_KEY) &&
				this.enabled !== this.configurationService.getValue<boolean>(EditorGroupWatermark.SETTINGS_KEY)
			) {
				this.render();
			}
		}));

		this._register(this.contextService.onDidChangeWorkbenchState(workbenchState => {
			if (this.workbenchState !== workbenchState) {
				this.workbenchState = workbenchState;
				this.render();
			}
		}));

		this._register(this.storageService.onWillSaveState(e => {
			if (e.reason === WillSaveStateReason.SHUTDOWN) {
				const entries = [...emptyWindowEntries, ...workspaceEntries, ...otherEntries];
				for (const entry of entries) {
					const when = isWeb ? entry.when?.web : entry.when?.native;
					if (when) {
						this.cachedWhen[entry.id] = this.contextKeyService.contextMatchesRules(when);
					}
				}

				this.storageService.store(EditorGroupWatermark.CACHED_WHEN, JSON.stringify(this.cachedWhen), StorageScope.PROFILE, StorageTarget.MACHINE);
			}
		}));
	}

	private render(): void {
		try {
			this.enabled = this.configurationService.getValue<boolean>(EditorGroupWatermark.SETTINGS_KEY);

			clearNode(this.shortcuts);
			clearNode(this.actionCardsContainer);
			clearNode(this.recentSection);
			this.transientDisposables.clear();

			if (!this.enabled) {
				return;
			}

			if (this.workbenchState === WorkbenchState.EMPTY) {
				this.renderEmptyWindow();
			} else {
				this.renderWorkspace();
			}
		} catch (e) {
			console.error('Watermark render error:', e);
		}
	}

	private renderEmptyWindow(): void {
		this.renderActionCards();
		this.renderRecentProjects();
	}

	private renderWorkspace(): void {
		const entries = this.filterEntries(workspaceEntries);
		if (entries.length < EditorGroupWatermark.MINIMUM_ENTRIES) {
			const additionalEntries = this.filterEntries(otherEntries);
			shuffle(additionalEntries);
			entries.push(...additionalEntries.slice(0, EditorGroupWatermark.MINIMUM_ENTRIES - entries.length));
		}

		const box = append(this.shortcuts, $('.watermark-box'));

		const update = () => {
			clearNode(box);
			this.keybindingLabels.clear();

			for (const entry of entries) {
				const keys = this.keybindingService.lookupKeybinding(entry.id);
				if (!keys) {
					continue;
				}

				const dl = append(box, $('dl'));
				const dt = append(dl, $('dt'));
				dt.textContent = entry.text;

				const dd = append(dl, $('dd'));

				const label = this.keybindingLabels.add(new KeybindingLabel(dd, OS, { renderUnboundKeybindings: true, ...defaultKeybindingLabelStyles }));
				label.set(keys);
			}
		};

		update();
		this.transientDisposables.add(this.keybindingService.onDidUpdateKeybindings(update));
	}

	private renderActionCards(): void {
		const cardsBox = append(this.actionCardsContainer, $('.action-cards-box'));

		for (const card of actionCards) {
			const cardElement = append(cardsBox, $('.action-card'));
			cardElement.setAttribute('data-command', card.command);

			const iconElement = append(cardElement, $('.action-card-icon'));
			const iconSvg = icons[card.icon];
			if (iconSvg) {
				const svgEl = this.createSvgFromMarkup(iconSvg);
				if (svgEl) {
					iconElement.appendChild(svgEl);
				}
			}

			const titleElement = append(cardElement, $('.action-card-title'));
			titleElement.textContent = card.title;

			const descElement = append(cardElement, $('.action-card-desc'));
			descElement.textContent = card.description;

			this._register(addDisposableListener(cardElement, EventType.CLICK, () => {
				this.commandService.executeCommand(card.command);
			}));
		}
	}

	private renderRecentProjects(): void {
		const recentFiles = this.getRecentFiles();

		if (recentFiles.length === 0) {
			return;
		}

		const section = append(this.recentSection, $('.recent-projects'));
		const title = append(section, $('.recent-title'));
		title.textContent = 'Recent Projects';

		const list = append(section, $('.recent-list'));
		const itemsToShow = recentFiles.slice(0, MAX_RECENT_ITEMS);

		for (const item of itemsToShow) {
			const listItem = append(list, $('.recent-item'));

			const nameContainer = append(listItem, $('.recent-item-name'));
			const iconSpan = append(nameContainer, $('span.recent-item-icon'));
			const folderSvg = icons['folder'];
			if (folderSvg) {
				const svgEl = this.createSvgFromMarkup(folderSvg);
				if (svgEl) {
					iconSpan.appendChild(svgEl);
				}
			}

			const nameSpan = append(nameContainer, $('span'));
			nameSpan.textContent = item.name;

			if (item.time) {
				const timeSpan = append(listItem, $('.recent-item-time'));
				timeSpan.textContent = item.time;
			}
		}

		if (recentFiles.length > MAX_RECENT_ITEMS) {
			const showMore = append(section, $('.show-more'));
			showMore.textContent = 'Show More Projects...';
		}
	}

	private getRecentFiles(): Array<{ name: string; time?: string }> {
		try {
			const recentJson = this.storageService.get('workbench.history', StorageScope.PROFILE);
			if (recentJson) {
				const recent = JSON.parse(recentJson);
				if (Array.isArray(recent)) {
					return recent.slice(0, 10).map((item: { label?: string; fileUri?: string; folderUri?: string }) => ({
						name: item.label || item.fileUri || item.folderUri || 'Unknown',
						time: undefined,
					}));
				}
			}
		} catch {
			// ignore
		}
		return [];
	}

	private createSvgFromMarkup(svgMarkup: string): SVGSVGElement | undefined {
		try {
			const viewBoxMatch = svgMarkup.match(/viewBox="([^"]*)"/);
			const viewBox = viewBoxMatch ? viewBoxMatch[1] : '0 0 24 24';

			const svgNS = 'http://www.w3.org/2000/svg';
			const svg = document.createElementNS(svgNS, 'svg');
			svg.setAttribute('viewBox', viewBox);
			svg.setAttribute('fill', 'none');
			svg.setAttribute('xmlns', svgNS);
			svg.style.width = '100%';
			svg.style.height = '100%';

			const pathMatch = svgMarkup.match(/<path\s+[^>]*\/>/g);
			if (pathMatch) {
				for (const p of pathMatch) {
					const dMatch = p.match(/d="([^"]*)"/);
					if (dMatch) {
						const path = document.createElementNS(svgNS, 'path');
						path.setAttribute('d', dMatch[1]);

						const fillMatch = p.match(/fill="([^"]*)"/);
						const strokeMatch = p.match(/stroke="([^"]*)"/);
						const strokeWidthMatch = p.match(/stroke-width="([^"]*)"/);
						const strokeLinecapMatch = p.match(/stroke-linecap="([^"]*)"/);
						const strokeLinejoinMatch = p.match(/stroke-linejoin="([^"]*)"/);

						if (fillMatch) {
							path.setAttribute('fill', fillMatch[1]);
						}
						if (strokeMatch) {
							path.setAttribute('stroke', strokeMatch[1]);
						}
						if (strokeWidthMatch) {
							path.setAttribute('stroke-width', strokeWidthMatch[1]);
						}
						if (strokeLinecapMatch) {
							path.setAttribute('stroke-linecap', strokeLinecapMatch[1]);
						}
						if (strokeLinejoinMatch) {
							path.setAttribute('stroke-linejoin', strokeLinejoinMatch[1]);
						}

						svg.appendChild(path);
					}
				}
			}
			return svg;
		} catch {
			return undefined;
		}
	}

	private filterEntries(entries: WatermarkEntry[]): WatermarkEntry[] {
		const filteredEntries = entries
			.filter(entry => {
				if (this.cachedWhen[entry.id]) {
					return true;
				}

				const contextKey = isWeb ? entry.when?.web : entry.when?.native;
				return !contextKey || this.contextKeyService.contextMatchesRules(contextKey);
			})
			.filter(entry => !!CommandsRegistry.getCommand(entry.id))
			.filter(entry => !!this.keybindingService.lookupKeybinding(entry.id));

		return filteredEntries;
	}
}
