import { createCatalog } from "@copilotkit/a2ui-renderer";
import { definitions } from "./definitions";
import { renderers } from "./renderers";

export const CATALOG_ID = "copilotkit://pulse-task-catalog";

export const catalog = createCatalog(definitions, renderers, {
  catalogId: CATALOG_ID,
  includeBasicCatalog: true,
});
