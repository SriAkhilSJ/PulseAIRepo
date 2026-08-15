import { expect, test } from "@playwright/test";

test("agent UI renders the contrib contract and no activity graph", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("PulseAI", { exact: false }).first()).toBeVisible();
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute("href", "/pulseai-mark.svg");
  await expect(page.locator(".brand-mark circle")).toBeVisible();
  await expect(page.getByText("src/vs/workbench/contrib/pulseai/")).toBeVisible();
  await expect(page.getByText("Fix authentication redirect", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeVisible();
  await expect(page.locator("canvas")).toHaveCount(0);
  await expect(page.locator(".task-timeline")).toHaveCount(0);
});

test("native menu bar exposes Code OSS and Pulse commands", async ({ page }) => {
  await page.goto("/");
  await page.locator("summary").filter({ hasText: /^File$/ }).click();
  await expect(page.getByRole("menuitem", { name: /New Text File/ })).toBeVisible();
  await page.locator("summary").filter({ hasText: /^Pulse$/ }).click();
  await expect(page.getByRole("menuitem", { name: /Open Pulse Manager/ })).toBeVisible();
});

test("tool disclosures expand details and keep queued tools locked", async ({ page }) => {
  await page.goto("/");
  const read = page.locator('[data-tool-id="read-auth"]');
  await expect(read).not.toHaveAttribute("open", "");
  await read.locator("summary").click();
  await expect(read).toHaveAttribute("open", "");
  await expect(read.getByText("return redirect(destination);")).toBeVisible();

  const terminal = page.locator('[data-tool-id="terminal-auth-test"]');
  await expect(terminal).toHaveAttribute("open", "");
  await expect(terminal.getByText("$ npm test -- auth")).toBeVisible();
  await expect(terminal.getByRole("button", { name: "Open terminal" })).toBeVisible();

  const edit = page.locator('[data-tool-id="edit-session"]');
  await expect(edit).toHaveAttribute("open", "");
  await expect(edit.getByRole("button", { name: "Open native diff" })).toBeVisible();

  const verify = page.locator('[data-tool-id="verify-ui"]');
  await verify.locator("summary").click();
  await expect(verify).not.toHaveAttribute("open", "");
});

test("tool gallery exercises specialized renderer families", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Tool Gallery" }).click();
  await expect(page.getByText("34 runtime tools")).toBeVisible();

  const terminal = page.locator('[data-tool-name="run_terminal"]');
  await expect(terminal).toHaveAttribute("open", "");
  await expect(terminal.getByText("Exit code")).toBeVisible();

  const web = page.locator('[data-tool-name="web_fetch"]');
  await web.locator("summary").click();
  await expect(web.getByRole("button", { name: "Open source" })).toBeVisible();

  const browser = page.locator('[data-tool-name="browser_snapshot"]');
  await browser.locator("summary").click();
  await expect(browser.getByText("Welcome back")).toBeVisible();

  const subagent = page.locator('[data-tool-name="delegate_to_subagent"]');
  await subagent.locator("summary").click();
  await expect(subagent.getByRole("button", { name: "Open sub-agent tab" })).toBeVisible();
});

test("streaming run reaches approval and verification", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Replay stream" }).click();
  await expect(page.locator(".stream-caret")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeVisible({ timeout: 8_000 });
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByText("Change verified")).toBeVisible({ timeout: 5_000 });
  await expect(page.getByText("Verified", { exact: true }).first()).toBeVisible();
});

test("agent manager exposes hierarchy and evidence without a graph", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Agent Manager" }).click();
  await expect(page.getByText("Workspaces", { exact: true })).toBeVisible();
  await expect(page.getByText("Run inspector", { exact: true })).toBeVisible();
  await expect(page.getByText("SUB-AGENTS", { exact: true })).toBeVisible();
  await expect(page.getByText("Changed files", { exact: true })).toBeVisible();
  await expect(page.locator("canvas")).toHaveCount(0);
});

test("compact viewport keeps the agent interaction available", async ({ page }) => {
  await page.setViewportSize({ width: 420, height: 780 });
  await page.goto("/");
  await expect(page.getByText("Fix authentication redirect", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
});
