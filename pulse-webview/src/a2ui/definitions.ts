import { z } from "zod";
import type { CatalogDefinitions } from "@copilotkit/a2ui-renderer";

const DynString = z.union([z.string(), z.object({ path: z.string() })]);

export const definitions = {
  Card: {
    description: "A container card with a single child.",
    props: z.object({
      child: z.string(),
    }),
  },
  Title: {
    description: "A prominent heading for the Pulse task card.",
    props: z.object({
      text: DynString,
    }),
  },
  StatusBadge: {
    description: "A pill-styled status tag.",
    props: z.object({
      status: DynString,
    }),
  },
  PriorityTag: {
    description: "A priority label.",
    props: z.object({
      level: DynString,
    }),
  },
  AssigneeBadge: {
    description: "Assignee name badge.",
    props: z.object({
      name: DynString,
    }),
  },
  Button: {
    description: "An interactive button with an action event.",
    props: z.object({
      child: z.string().describe("The ID of the child component for the label."),
      variant: z.enum(["primary", "secondary", "ghost"]).optional(),
      action: z
        .union([
          z.object({
            event: z.object({
              name: z.string(),
              context: z.record(z.any()).optional(),
            }),
          }),
          z.null(),
        ])
        .optional(),
    }),
  },
} satisfies CatalogDefinitions;
