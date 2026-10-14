# Playwright check of the /onboarding redirect logic.
# MOCK — not real data: every /api/** call is intercepted and answered from the
# repo fixture (frontend-v5/e2e/fixtures/user-profile-charting.json) so the page
# logic can be exercised without a real session. Nothing here proves backend behaviour.
import asyncio, json, sys
from playwright.async_api import async_playwright
ME = json.load(open("/fixtures/user-profile-charting.json"))
async def run(p, base, label, path, onboarded):
    b = await p.chromium.launch(); pg = await b.new_page()
    async def handle(route):
        req = route.request; origin = req.headers.get("origin", "*")
        h = {"access-control-allow-origin": origin, "access-control-allow-credentials": "true",
             "access-control-allow-headers": "*", "access-control-allow-methods": "*", "content-type": "application/json"}
        if req.method == "OPTIONS": return await route.fulfill(status=204, headers=h)
        u = req.url.split("?")[0]
        if u.endswith("/api/auth/me"): body = dict(ME, onboarding_completed=onboarded)
        elif u.endswith("/api/onboarding/state"): body = {"onboarding_completed": onboarded}
        else: body = {}
        await route.fulfill(status=200, headers=h, body=json.dumps(body))
    await pg.route("**/api/**", handle)
    await pg.goto(base + path, wait_until="domcontentloaded", timeout=60000)
    await pg.wait_for_timeout(3500)
    url = pg.url.replace(base, "")
    connect = await pg.get_by_text("Bring your investments in.").count()
    file_inputs = await pg.locator("input[type=file]").count()
    print(f"{label:<58} → url={url:<28} connect_step={bool(connect)} file_input={file_inputs}")
    await b.close(); return url, bool(connect), file_inputs
async def main():
    base = sys.argv[1]; fails = 0
    async with async_playwright() as p:
        u, c, f = await run(p, base, "TC1 onboarded, /onboarding (no intent)", "/v5/onboarding", True)
        fails += not u.startswith("/v5/lite")
        u, c, f = await run(p, base, "TC2 onboarded, /onboarding?tab=upload", "/v5/onboarding?tab=upload", True)
        fails += not (u.startswith("/v5/onboarding") and c and f >= 1)
        u, c, f = await run(p, base, "TC3 onboarded, /onboarding?tab=gmail", "/v5/onboarding?tab=gmail", True)
        fails += not (u.startswith("/v5/onboarding") and c)
        u, c, f = await run(p, base, "TC4 NOT onboarded, /onboarding (persona step first)", "/v5/onboarding", False)
        fails += not (u.startswith("/v5/onboarding") and not c)
    print("RESULT:", "ALL PASS" if not fails else f"{fails} FAILED"); sys.exit(1 if fails else 0)
asyncio.run(main())
