import { test, expect } from '@playwright/test';
test('pulse webview renders and chats', async ({ page }) => {
  page.on('console', msg => console.log('BROWSER CONSOLE:', msg.text()));
  page.on('pageerror', err => console.log('PAGEERROR:', err.message));
  await page.goto('http://localhost:5173', { waitUntil: 'domcontentloaded', timeout: 15000 });
  await page.waitForTimeout(3000);
  await expect(page.locator('text=PulseAI')).toBeVisible({ timeout: 10000 });
  const input = page.locator('[contenteditable="true"], textarea, div[role="textbox"]').first();
  await expect(input).toBeVisible({ timeout: 10000 });
  await input.click();
  await page.keyboard.type('hello');
  await page.keyboard.press('Enter');
  // wait for any agent response (text appears) - allow sarvam call
  await page.waitForTimeout(12000);
  const body = await page.content();
  console.log('BODY LEN', body.length);
  await page.screenshot({ path: 'D:/pulseAIagent/browser-verify.png', fullPage: true });
  // check for no error boundary
  await expect(page.locator('text=Agent default not found')).toHaveCount(0);
});
