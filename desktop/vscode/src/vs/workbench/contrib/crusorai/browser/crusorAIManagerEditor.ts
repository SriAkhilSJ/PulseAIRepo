/*---------------------------------------------------------------------------------------------
 * Full-width Crusor Manager hosted as an editor tab inside CrusorAI IDE.
 *--------------------------------------------------------------------------------------------*/

import * as DOM from '../../../../base/browser/dom.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { IEditorGroup } from '../../../services/editor/common/editorGroupsService.js';
import { CRUSOR_AI_MANAGER_EDITOR_ID } from '../common/crusorAI.js';
import { ICrusorAIRendererService } from '../common/crusorAIRendererService.js';
import { installCrusorTheme } from './crusorTheme.js';

export class CrusorAIManagerEditor extends EditorPane {
	static readonly ID = CRUSOR_AI_MANAGER_EDITOR_ID;
	private root: HTMLElement | undefined;

	constructor(
		group: IEditorGroup,
		@ITelemetryService telemetryService: ITelemetryService,
		@IThemeService private readonly crusorThemeService: IThemeService,
		@IStorageService storageService: IStorageService,
		@ICrusorAIRendererService private readonly crusorAIRendererService: ICrusorAIRendererService,
	) {
		super(CrusorAIManagerEditor.ID, group, telemetryService, crusorThemeService, storageService);
	}

	protected createEditor(parent: HTMLElement): void {
		this.root = DOM.append(parent, DOM.$('.crusorai-manager-editor.crusorai-render-root'));
		// Same derived palette as the pane: seeds from the live theme, never
		// hardcoded (hermes seed→token machine).
		this._register(installCrusorTheme(this.root, this.crusorThemeService));
		this.root.dataset.surface = 'manager';
		this.root.setAttribute('role', 'region');
		this.root.setAttribute('aria-label', 'Crusor Manager');
		this._register(this.crusorAIRendererService.mount(this.root, 'manager'));
	}

	override layout(size: DOM.Dimension): void {
		if (!this.root) {
			return;
		}
		this.root.style.width = `${size.width}px`;
		this.root.style.height = `${size.height}px`;
	}
}
