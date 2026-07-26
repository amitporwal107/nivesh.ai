import { test, expect, Page, APIRequestContext } from '@playwright/test';

// T17 — the 3 demos, driven through the real UI.
// Serial: these steps share one server-side exam window.
test.describe.configure({ mode: 'serial' });

const setWindow = (request: APIRequestContext, minutes_from_now: number) =>
  request.post('/api/admin/set_window', { data: { minutes_from_now, duration_minutes: 30 } });

async function openPaper(page: Page, candidate: string, passphrase: string) {
  await page.goto('/terminal');
  await page.getByTestId('candidate-select').selectOption(candidate);
  await page.getByTestId('passphrase').fill(passphrase);
  await page.getByTestId('get-paper').click();
}

test('D2a — pre-window key request is refused, paper stays sealed', async ({ page, request }) => {
  await setWindow(request, 5);
  await openPaper(page, 'C1', 'finger1');
  await expect(page.locator('.msg.err')).toContainText('REFUSED_EARLY');
  await expect(page.getByTestId('watermark')).toBeHidden();
});

test('D2b — wrong biometric is refused', async ({ page, request }) => {
  await setWindow(request, 0);
  await openPaper(page, 'C1', 'not-my-finger');
  await expect(page.locator('.msg.err')).toContainText('REFUSED_AUTH');
  await expect(page.getByTestId('watermark')).toBeHidden();
});

test('D2c — window + biometric releases the key and renders the watermarked paper', async ({ page, request }) => {
  await setWindow(request, 0);
  await openPaper(page, 'C1', 'finger1');
  await expect(page.getByTestId('watermark')).toHaveText('CANDIDATE-C1');
  await expect(page.locator('#questions .q')).toHaveCount(10);

  // answer + submit round-trips through the server-side key service
  await page.locator('#questions .q').first().locator('input[type=radio]').first().check();
  await page.getByTestId('submit').click();
  await expect(page.locator('.msg.ok')).toContainText(/Submitted — score \d+\/10/);
});

test('D1 — C2 gets a different paper; dashboard shows equal difficulty', async ({ page, request }) => {
  await setWindow(request, 0);

  await openPaper(page, 'C1', 'finger1');
  const c1 = await page.locator('#questions .q p').allTextContents();

  await openPaper(page, 'C2', 'finger2');
  await expect(page.getByTestId('watermark')).toHaveText('CANDIDATE-C2');
  const c2 = await page.locator('#questions .q p').allTextContents();

  expect(c1).toHaveLength(10);
  expect(c2).toEqual(expect.not.arrayContaining([c1[0]]));  // C1's Q1 is not anywhere in C2
  expect(c1.join('|')).not.toEqual(c2.join('|'));

  await page.goto('/dashboard');
  await expect(page.getByTestId('parity')).toContainText('< tolerance 0.15 ✓');
  await expect(page.getByTestId('candidates-table').locator('tr')).toHaveCount(6);
});

test('D3 — a leaked paper names its leaker; a fake one is stamped FABRICATED', async ({ page, request }) => {
  await setWindow(request, 0);
  await openPaper(page, 'C2', 'finger2');

  // the leak: exactly what a candidate could carry out of the hall as text
  await page.getByTestId('leak').click();
  const leaked = await page.getByTestId('leaktext').inputValue();
  expect(leaked).toContain('CANDIDATE-C2');

  await page.goto('/dashboard');
  await page.getByTestId('forensics-input').fill(leaked);
  await page.getByTestId('forensics-run').click();
  const verdict = page.getByTestId('forensics-result');
  await expect(verdict).toContainText('IDENTIFIED');
  await expect(verdict).toContainText('C2 (rohan)');
  await expect(verdict).toContainText('order match 10/10');

  await page.getByTestId('forensics-input').fill(
    'Lorem ipsum dolor sit amet. LEAKED PAPER, 100% genuine, forward to all.');
  await page.getByTestId('forensics-run').click();
  await expect(verdict).toContainText('FABRICATED');
});

test('ledger — chain verifies clean from the dashboard', async ({ page }) => {
  await page.goto('/dashboard');
  await page.getByTestId('ledger-verify').click();
  await expect(page.getByTestId('ledger-verify-result')).toContainText('chain intact');
  await expect(page.getByTestId('ledger-table').locator('tr').first()).toBeVisible();
});
