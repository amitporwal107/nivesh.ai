# Intern Exercise — Validate the Research app (UI + DATA / source-of-truth)

**Owner (mentor):** ______________  **Intern:** ______________  **Date started:** __________

> **What you are testing:** the **Research** surface of the app (it calls itself
> *"Filings Intelligence"*). It shows Indian-market corporate announcements/filings, a
> personalised *"Read for you today"* feed, an AI summary per filing, and a portfolio-held
> badge. Browser URL on staging: **`/v5/research`**.
>
> **The whole point of this exercise:** the app doesn't just *display* filings — it
> *derives* things from them (an AI summary, a "headline metric", a doc-type, a
> portfolio-held badge, a sort order). Your job is to prove, for each thing the app shows,
> that **(a) the UI works** and **(b) the data behind it is real and matches the original
> BSE/NSE filing** — not a plausible-looking hallucination.
>
> A filing that *renders nicely* but whose AI summary invents a number that isn't in the
> PDF is a **FAIL**, not a pass. That distinction is the skill we're testing.

---

## 0. Golden rules (read before you start)

1. **"It loaded" is not "it's correct."** Every claim needs two checks: the screen worked
   **and** the data is true against the original source.
2. **The original BSE/NSE document is the source of truth** — never the app, never this
   doc, never what you remember. When in doubt, open the exchange PDF.
3. **Never fake evidence.** Paste the real link / screenshot / API output you actually got.
   If something is blocked, write `BLOCKED: <why>` — that is a valid, honest result.
4. **A discrepancy is a finding, not a failure of yours.** Log it. Finding a real data
   bug is the best possible outcome of this exercise.
5. **Expect known rough edges (log them, don't panic):** some announcements have a blank
   category/impact (so they sort last), and some older BSE attachment links 404 — note it
   in the bug log and move on.

---

## 1. Setup checklist (do this first — tick each box)

| # | Step | How | Done |
|---|------|-----|:----:|
| S1 | Get staging URL + a login | Ask your mentor for the staging host (e.g. `https://staging.niveshcopilot.com`) and a test account / magic-link. | ☐ |
| S2 | Open the Research tab | Log in, go to **`/v5/research`** (or tap the **Research** tab in the mobile bottom nav, after *Tips*). | ☐ |
| S3 | Confirm you can see the feed | You should see *"Read for you today"* cards and an *All filings* list. | ☐ |
| S4 | Get your API session token | In the browser devtools → Application → Cookies, copy the value of **`session_token`**. You'll need it for the API checks in Section 4. | ☐ |
| S5 | Bookmark the two source-of-truth sites | **BSE:** bseindia.com → *Corporates → Corporate Announcements*. **NSE:** nseindia.com → *Companies → Corporate Filings → Announcements*. | ☐ |
| S6 | Pick a test portfolio | Ask your mentor which test account has holdings (needed to check the **portfolio-held badge**). Write the held companies here: ________________ | ☐ |

> If S1/S6 are blocked (no token, no test portfolio), **stop and tell your mentor** —
> write `BLOCKED` in the relevant rows below rather than guessing.

---

## 2. UI functional checklist

Walk each feature, do the action, compare to *Expected*, tick PASS or FAIL, and note what
you actually saw. The `testid` column is the element's `data-testid` (ask your mentor how
to see it in devtools; you don't strictly need it, but it removes ambiguity about which
element to click).

| # | Feature | testid | Do this | Expected | Result | Notes / what you saw |
|---|---------|--------|---------|----------|:------:|----------------------|
| U1 | Research tab loads | — | Open `/v5/research` | Feed + All-filings render, no error/blank screen | ☐ P ☐ F | |
| U2 | "Read for you today" | `today-toggle`, `signal-card` | Look at the *Read for you today* row; toggle **today** ↔ **latest** | Today shows only *today's* filings; latest shows recent ones; up to 3 cards | ☐ P ☐ F | |
| U3 | Click-to-drawer | `signal-drawer` | Click a signal card | A slide-over drawer opens with the filing's summary/detail | ☐ P ☐ F | |
| U4 | Portfolio-held badge | `portfolio-badge` | Find a card for a company in your test portfolio (S6) | An **"IN YOUR PORTFOLIO"** pill shows on the card and in the drawer | ☐ P ☐ F | |
| U5 | Company search scopes feed | `filings-search`, `company-suggestion` | Type a company name, pick a suggestion | Feed narrows to that company; a **scope chip** appears; "Read for you" row hides | ☐ P ☐ F | |
| U6 | Clear scope | `clear-company` | Click the ✕ on the scope chip | Feed returns to the full "Read for you" view | ☐ P ☐ F | |
| U7 | Thematic starters | `thematic-starters`, `thematic-starter` | Click a starter chip; try the **Curated / History / Favorites** tabs | Chip runs an Ask; History/Favorites tabs switch content | ☐ P ☐ F | |
| U8 | Ask bar (copilot) | `ask-input`, `ask-submit`, `copilot-answer` | Type a question, submit | An answer renders with **source chips** you can click | ☐ P ☐ F | |
| U9 | All-filings sort | `sort-material`, `sort-latest` | Toggle **MATERIAL** ↔ **LATEST** | Material puts high-impact first; Latest is newest-first | ☐ P ☐ F | |
| U10 | Filing AI-insight panel | `filing-row`, `toggle-insight`, `insight-panel` | Expand a filing row | Panel shows summary + sections + **page citations** | ☐ P ☐ F | |
| U11 | Documents library | `documents-panel`, `doc-row`, `doc-download` | Open a company's documents; click download | The **original filing PDF** opens/downloads | ☐ P ☐ F | |
| U12 | Alerts screen | `alerts-screen`, `type-…`, `channel-email` | Open Alerts; toggle a type/channel | Preference saves (note: **delivery is intentionally OFF** — a notice says so; that's expected) | ☐ P ☐ F | |

---

## 3. DATA / source-of-truth checklist  ⭐ (the core of this exercise)

Pick **5 filings** from the app (mix: at least 2 from *Read for you today*, 2 from *All
filings*, 1 that shows the **portfolio badge**). For **each one**, fill a validation block
below.

**The method for each filing:**
1. In the app, record what it shows (company, ticker, date, doc type, the AI summary, the
   headline metric, whether it has a portfolio badge, and the page citation).
2. Open the **original document** — click `doc-download` / the source link in the app **and**
   independently find the *same* announcement on **BSE** or **NSE** (Section 1, S5).
3. Compare field-by-field against the PDF. **The PDF wins.**
4. Mark each row ✓ (matches) / ✗ (mismatch) / n/a, and paste the source link + screenshot.

> **Read the AI summary critically.** Is every number in the summary/"headline metric"
> actually stated in the PDF? Is the cited page the page it's really on? Is the doc-type
> right (e.g. is a "Board Meeting Intimation" mislabelled as "Financial Results")? An
> invented or misplaced number = **FAIL**, and it's exactly what we want you to catch.

### Filing validation block  — copy this block once per filing (×5)

**Filing #__**

| Field | What the APP shows | What the ORIGINAL BSE/NSE source shows | Match? |
|-------|--------------------|-----------------------------------------|:------:|
| Company name | | | ☐✓ ☐✗ |
| Ticker / scrip | | | ☐✓ ☐✗ |
| Filed date/time | | | ☐✓ ☐✗ |
| Doc type / subject | | | ☐✓ ☐✗ |
| AI "Read for you" summary is faithful (no invented facts) | | | ☐✓ ☐✗ |
| "Headline metric" is actually in the PDF | | | ☐✓ ☐✗ |
| Page citation points to the right page | | | ☐✓ ☐✗ |
| Portfolio-held badge is correct (company really held / really not) | | | ☐✓ ☐✗ |
| Source-of-truth link (BSE/NSE URL or PDF): | | | |
| Screenshot filename(s): | | | |

**Filing verdict:** ☐ PASS (all applicable rows ✓) ☐ FAIL — discrepancy noted in Section 5

*(Repeat the block above for filings #2–#5.)*

---

## 4. API / DB spot-check (prove the UI isn't lying)

Hit the real endpoints and confirm they return the same data the UI showed you. Use your
`session_token` from S4. Replace `<HOST>` with the staging host.

| # | Endpoint | Command (fill in & run) | Check | Result |
|---|----------|--------------------------|-------|:------:|
| A1 | Today's signals | `curl -sk '<HOST>/api/filings/signals?today_only=true' -H 'Cookie: session_token=<TOKEN>'` | Same ≤3 companies/dates as the *Read for you today* cards (U2/U3) | ☐ P ☐ F |
| A2 | Feed | `curl -sk '<HOST>/api/filings/feed' -H 'Cookie: session_token=<TOKEN>'` | Row count/companies match the *All filings* list | ☐ P ☐ F |
| A3 | Company search | `curl -sk '<HOST>/api/filings/companies/search?q=<NAME>' -H 'Cookie: session_token=<TOKEN>'` | Returns the company you scoped to in U5 | ☐ P ☐ F |
| A4 | Insight detail | `curl -sk '<HOST>/api/filings/<ANNOUNCEMENT_ID>/insights' -H 'Cookie: session_token=<TOKEN>'` | Summary/metric/`source_url` match the drawer/panel from U3/U10 — and `source_url` is the **exchange PDF** you validated in Section 3 | ☐ P ☐ F |
| A5 | Portfolio-held | `curl -sk '<HOST>/api/filings/portfolio-held' -H 'Cookie: session_token=<TOKEN>'` | The held names/symbols explain every `portfolio-badge` you saw (U4) | ☐ P ☐ F |

> **Where the data comes from** (context, so a mismatch tells you *where* to look):
> the feed & signals read **`nidp.corporate_announcements`**; the AI summary/metric read
> **`nidp.corporate_event_signals`** joined to **`nidp.documents`** (whose `source_url`
> is the original BSE/NSE PDF). If the app and the PDF disagree, note whether the app
> value came from the announcement row or the AI signal — your mentor will point you at
> the right table.

---

## 5. Bug / discrepancy log

Log everything that failed or looked wrong. One row per issue. **Severity:** Blocker /
Major / Minor / Cosmetic.

| # | Where (U#/Filing#/A#) | What you expected | What actually happened | Original-source evidence (link) | Screenshot | Severity |
|---|-----------------------|-------------------|------------------------|----------------------------------|-----------|----------|
| B1 | | | | | | |
| B2 | | | | | | |
| B3 | | | | | | |

---

## 6. Final verdict & sign-off

- UI checklist (Section 2): ____ / 12 PASS
- Data / source-of-truth (Section 3): ____ / 5 filings PASS
- API spot-checks (Section 4): ____ / 5 PASS
- Bugs found: ____ (Blockers: ___ Major: ___ Minor: ___ Cosmetic: ___)

**One-paragraph summary** (what you tested, what's solid, what's broken, your biggest
data-correctness concern):

____________________________________________________________________________________

____________________________________________________________________________________

**Overall verdict:** ☐ PASS  ☐ PASS-with-minor-bugs  ☐ FAIL — data does not match source

Intern: ______________   Reviewed by mentor: ______________   Date: __________

---
*How you'll be graded: not on how many boxes are green, but on whether you actually
opened the original filings, caught real discrepancies, and reported them honestly —
including anything you couldn't verify.*
