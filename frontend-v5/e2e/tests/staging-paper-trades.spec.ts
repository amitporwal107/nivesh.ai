/**
 * Research → Paper on REAL staging (TC-P30 in test_reports/paper_trades_engine_20260918_1338.md). No mocks: the page runs
 * against the staging app and DaaS, and every checked cell is compared with the payload the page itself received.
 *
 * Needs an allowlisted owner session: STAGING_SESSION_FILE=<file holding the session_token>. Skipped without it.
 */
import { test, expect, type Page, type Response } from "@playwright/test";
import fs from "fs";

const UI = "https://staging.niveshcopilot.com:8443";
const FILE = process.env.STAGING_SESSION_FILE;
const BANNED = /\b(buy|sell|recommend(ed|ation)?|multibagger|top pick|sure[- ]shot|guaranteed)\b/i;
const pct2 = (x: number) => { const t = Math.abs(x * 100).toFixed(2); return x > 0 && Number(t) !== 0 ? `+${t}%` : x < 0 && Number(t) !== 0 ? `−${t}%` : "0.00%"; };
const p1 = (x: number) => (x * 100 < 0.1 ? "<0.1%" : `${(x * 100).toFixed(1)}%`);
const rs = (x: number) => `₹${x.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

test.skip(!FILE, "STAGING_SESSION_FILE not set");
test.describe.configure({ mode: "serial" });

async function login(page: Page) {
  const token = fs.readFileSync(FILE as string, "utf-8").trim();
  await page.context().addCookies([{ name: "session_token", value: token, domain: "staging.niveshcopilot.com", path: "/", secure: true, httpOnly: true }]);
}
const json = async (r: Response) => (await r.json()).data;
const isPortfolio = (r: Response, q: string) => r.url().includes("/api/paper-trades/portfolio") && r.url().includes(q) && r.status() === 200;

async function cleanText(page: Page) {
  const t = await page.getByTestId("paper-screen").innerText();
  expect(t).not.toMatch(/NaN|undefined|\[object Object\]|Infinity/);
  expect(t.replace(await page.getByTestId("pt-disclaimer").innerText(), "")).not.toMatch(BANNED);
}

test("TC-P30 real staging: today's portfolio, older session, trade path and evaluation equal the payloads", async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await login(page);
  await page.goto(`${UI}/v5/research`);
  const first = page.waitForResponse((r) => isPortfolio(r, "sample=forward") && r.url().includes("P5-NEXT"));
  const liveP = page.waitForResponse((r) => r.url().includes("/api/paper-trades/live") && r.status() === 200);
  await page.getByTestId("rail-paper").click();
  const pf = await json(await first);
  const live = await json(await liveP);
  await expect(page.getByTestId("paper-screen")).toBeVisible();
  await expect(page.locator('[data-testid^="pt-row-"]')).toHaveCount(pf.positions.length);
  await expect(page.getByTestId("pt-provenance")).toContainText(pf.provenance.model_version);
  for (const p of pf.positions) {
    await expect(page.getByTestId(`pt-row-${p.symbol}`)).toContainText(p1(p.movement_probability));
    if (p.entry_price == null) await expect(page.getByTestId(`pt-entry-${p.symbol}`)).toContainText("open of");
    else await expect(page.getByTestId(`pt-entry-${p.symbol}`)).toHaveText(rs(p.entry_price));
  }
  for (const l of live.positions) await expect(page.getByTestId(`pt-live-${l.symbol}`)).toHaveText(l.label);
  if (!pf.provenance.counts_toward_evaluation) await expect(page.getByTestId("pt-notcounted-banner")).toBeVisible();
  await cleanText(page);

  // an entered session: official entries and the stored EOD-1 exit
  await page.getByTestId("pt-portfolio-P10-NEXT").click();
  await expect(page.locator('[data-testid^="pt-row-"]').first()).toBeVisible();
  const older = page.waitForResponse((r) => isPortfolio(r, "prediction_date=2026-09-16"));
  await page.getByTestId("pt-date").selectOption("2026-09-16");
  const po = await json(await older);
  for (const p of po.positions) {
    await expect(page.getByTestId(`pt-entry-${p.symbol}`)).toHaveText(rs(p.entry_price));
    await expect(page.getByTestId(`pt-ret-${p.symbol}`)).toContainText(pct2(p.exits["EOD-1"].net_return));
  }
  await cleanText(page);

  // trade path from the trade record
  const sym = po.positions[0].symbol;
  const tr = page.waitForResponse((r) => r.url().includes(`/api/paper-trades/trades/${po.positions[0].trade_id}`) && r.status() === 200);
  await page.getByTestId(`pt-open-${sym}`).click();
  const t = await json(await tr);
  await expect(page.getByTestId("pt-trade-symbol")).toHaveText(sym);
  await expect(page.locator('[data-testid^="pt-path-"]')).toHaveCount(t.observations.length);
  await expect(page.getByTestId("pt-path-0")).toContainText(pct2(t.observations[0].return_from_entry));
  await expect(page.getByTestId("pt-exit-EOD-1")).toContainText(pct2(t.exits["EOD-1"].net_return));
  await expect(page.getByTestId("pt-log").locator("li")).toHaveCount(t.events.length);
  await cleanText(page);

  // evaluation: replay payload, never pooled with forward
  await page.getByTestId("pt-portfolio-P5-NEXT").click();
  const evP = page.waitForResponse((r) => r.url().includes("/api/paper-trades/evaluation") && r.url().includes("sample=replay") && r.status() === 200);
  await page.getByTestId("pt-view-eval").click();
  await page.getByTestId("pt-sample-replay").click();
  const ev = (await json(await evP)).evaluation;
  const head = ev.modes.find((m: { mode: string }) => m.mode === "EOD-1");
  await expect(page.getByTestId("pt-statement")).toContainText(ev.statement.text);
  await expect(page.getByTestId("pt-eval-net")).toHaveText(pct2(head.net_mean));
  await expect(page.getByTestId("pt-eval-edge")).toHaveText(pct2(head.edge_vs_a_all.mean));
  await expect(page.locator('[data-testid^="pt-eval-mode-"]')).toHaveCount(ev.modes.length);
  await cleanText(page);
});

test("TC-P30 real staging at 390 px: no sideways scroll on the three screens", async ({ page }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await page.goto(`${UI}/v5/research`);
  await page.getByTestId("mnav-paper").click();
  await expect(page.locator('[data-testid^="pt-row-"]').first()).toBeVisible({ timeout: 30_000 });
  const noScroll = () => page.evaluate(() => {
    const doc = document.documentElement;
    const region = (document.querySelector('[data-testid="paper-screen"]') as HTMLElement).parentElement as HTMLElement;
    return doc.scrollWidth <= doc.clientWidth + 1 && region.scrollWidth <= region.clientWidth + 1;
  });
  expect(await noScroll()).toBeTruthy();
  await page.getByTestId("pt-view-trade").click();
  await expect(page.getByTestId("pt-trade")).toBeVisible();
  expect(await noScroll()).toBeTruthy();
  await page.getByTestId("pt-view-eval").click();
  await expect(page.getByTestId("pt-statement")).toBeVisible({ timeout: 30_000 });
  expect(await noScroll()).toBeTruthy();
});
