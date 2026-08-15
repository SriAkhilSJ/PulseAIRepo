import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  outputDir: "/tmp/pulseai-ui-test-results",
  fullyParallel: false,
  timeout: 20_000,
  expect: { timeout: 6_000 },
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: true,
    timeout: 30_000,
  },
});
