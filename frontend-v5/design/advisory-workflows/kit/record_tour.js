// Record the cinematic tour to a video by driving it in headless Chromium.
const { chromium } = require('/app/frontend-v5/node_modules/playwright');
const path = require('path');
const fs = require('fs');

const BASE = '/app/.claude/workspace/advisory-workflows';
const VIDDIR = path.join(BASE, 'video');

(async () => {
  fs.mkdirSync(VIDDIR, { recursive: true });
  const browser = await chromium.launch({ args: ['--force-color-profile=srgb'] });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 },
    deviceScaleFactor: 2,
    colorScheme: 'light',
    recordVideo: { dir: VIDDIR, size: { width: 1280, height: 720 } },
  });
  const page = await context.newPage();
  const url = 'file://' + path.join(BASE, 'tour.html') + '?chrome=0&autoplay=1&norepeat=1';
  await page.goto(url, { waitUntil: 'load' });

  const total = await page.evaluate(() => window.__tourTotalMs || 54000);
  console.log('tour total ms:', total);
  // wait for the tour to finish (with a safety cap)
  await page.waitForFunction(() => window.__tourDone === true, null, { timeout: total + 8000 })
    .catch(() => console.log('note: __tourDone not set, closing on timeout'));
  await page.waitForTimeout(600); // let the final frame settle

  const video = page.video();
  await context.close();          // finalizes the .webm
  const raw = await video.path();
  const dest = path.join(VIDDIR, 'nivesh-advisory-tour.webm');
  fs.renameSync(raw, dest);
  await browser.close();
  console.log('WEBM:', dest, fs.statSync(dest).size, 'bytes');
})().catch(e => { console.error('RECORD FAIL:', e); process.exit(1); });
