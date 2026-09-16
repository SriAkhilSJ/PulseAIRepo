/*---------------------------------------------------------------------------------------------
 * Desktop-only CrusorAI service registration. Kept out of workbench.common.main for web safety.
 *--------------------------------------------------------------------------------------------*/
import { localize } from '../../../../nls.js';
import { Extensions as ConfigurationExtensions } from '../../../../platform/configuration/common/configurationRegistry.js';
import { registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { ICrusorAIEngineService } from '../common/crusorAIEngineService.js';
import { CrusorAIEngineService } from './crusorAIEngineService.js';
registerSingleton(ICrusorAIEngineService, CrusorAIEngineService, 1 /* InstantiationType.Delayed */);
Registry.as(ConfigurationExtensions.Configuration).registerConfiguration({
    id: 'crusorai',
    title: localize('crusorAI.configuration.title', 'CrusorAI'),
    type: 'object',
    properties: {
        'crusorai.engineRoot': {
            type: 'string',
            default: '',
            scope: 2 /* ConfigurationScope.MACHINE */,
            description: localize('crusorAI.engineRoot', 'Absolute path to the CrusorAI engine package (must contain src/bridge). Falls back to the CRUSORAI_ENGINE_ROOT environment variable. Never the user workspace.'),
        },
        'crusorai.pythonPath': {
            type: 'string',
            default: '',
            scope: 2 /* ConfigurationScope.MACHINE */,
            description: localize('crusorAI.pythonPath', 'Python executable used for the local CrusorAI engine. Empty uses the platform default.'),
        },
        'crusorai.autoStart': {
            type: 'boolean',
            default: true,
            scope: 4 /* ConfigurationScope.WINDOW */,
            description: localize('crusorAI.autoStart', 'Start the local CrusorAI engine when the Crusor view is first opened.'),
        },
    },
});
