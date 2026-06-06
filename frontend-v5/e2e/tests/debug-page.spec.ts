import { test, expect } from "@playwright/test";
import { mockApi } from "../helpers/api-mock";

test("debug — see page content on /v5/dashboard", async ({ page }) => {
  const consoleErrs: string[] = [];
  const pageErrs: string[] = [];
  const requests: string[] = [];
  page.on("console", msg => { if (msg.type() === "error") consoleErrs.push(msg.text().substring(0, 200)); });
  page.on("pageerror", err => pageErrs.push(err.message.substring(0, 200)));
  page.on("requestfailed", req => requests.push("FAIL:" + req.url().substring(0, 100) + " " + req.failure()?.errorText));
  page.on("response", resp => { if (resp.status() === 404) requests.push("404:" + resp.url().substring(0, 100)); });

  await mockApi(page, "populated");
  await page.goto("/v5/dashboard");
  // Wait for networkidle with a long timeout
  try {
    await page.waitForLoadState("networkidle", { timeout: 25000 });
    console.log("NETWORKIDLE REACHED");
  } catch {
    console.log("NETWORKIDLE TIMEOUT - checking state anyway");
  }

  const url = page.url();
  const rootHtml = await page.locator("#root").innerHTML().catch(() => "NO_ROOT");
  const bodyText = await page.locator("body").innerText().catch(() => "BODY_ERR");
  const h1Text = await page.locator("h1").first().innerText().catch(() => "NO_H1");
  console.log("URL:", url);
  console.log("H1:", h1Text);
  console.log("Body text (first 500):", bodyText.substring(0, 500));
  console.log("Root HTML (first 300):", rootHtml.substring(0, 300));
  console.log("Console errors:", consoleErrs.slice(0, 5).join(" || "));
  console.log("Page errors:", pageErrs.slice(0, 5).join(" || "));
  console.log("Failed/404 requests:", requests.slice(0, 10).join(" || "));
  expect(true).toBe(true);
});

test("debug — see page content on /v5/ai-insights", async ({ page }) => {
  await mockApi(page, "populated");
  await page.goto("/v5/ai-insights");
  await page.waitForLoadState("networkidle");
  const url = page.url();
  const bodyText = await page.locator("body").innerText().catch(() => "ERROR");
  console.log("URL:", url);
  console.log("Body text (first 500):", bodyText.substring(0, 500));
  expect(true).toBe(true);
});

test("debug — see page content on /v5/chat", async ({ page }) => {
  await mockApi(page, "populated");
  await page.goto("/v5/chat");
  await page.waitForLoadState("networkidle");
  const url = page.url();
  const bodyText = await page.locator("body").innerText().catch(() => "ERROR");
  console.log("URL:", url);
  console.log("Body text (first 500):", bodyText.substring(0, 500));
  expect(true).toBe(true);
});
