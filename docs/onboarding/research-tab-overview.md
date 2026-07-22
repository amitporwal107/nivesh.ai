# The Research tab — what it does, how to use it, how to test it

*A one-page orientation. Pairs with the hands-on
[intern validation exercise](intern-research-app-validation-exercise.md).*

---

## TL;DR

The **Research** tab (the app calls it *"Filings Intelligence"*) is where a user reads
Indian-market **corporate filings/announcements** — board meetings, results, concall
transcripts, etc. — turned into something readable. It pulls the raw filings from the
exchanges (BSE/NSE), then layers **AI-derived** help on top: a short summary per filing,
a "headline metric", a personalised *"Read for you today"* shortlist, and an
*"in your portfolio"* badge. You can search a company, ask a question in plain English,
sort by what's material, and open the original PDF.

**The one idea to hold onto:** some of what you see is **raw** (came straight from the
exchange) and some is **derived** (an AI generated it from the PDF). Testing = confirming
the UI works **and** that the derived stuff is faithful to the original filing.

---

## Where it lives

| | |
|---|---|
| **URL (staging)** | `/v5/research` (login-gated — needs an account) |
| **Frontend** | `frontend-v5/src/pages/Research/index.tsx` (one file for the whole surface) |
| **Route** | `frontend-v5/src/routes.tsx` → `RequireAuth` → `ResearchPage` |
| **Backend** | `backend/routes/filings.py` (all endpoints under `/api/filings/...`) |
| **Nav** | mobile bottom-nav **Research** tab (after *Tips*) |

---

## What you see, and where the data comes from (raw vs derived)

| On screen | What it is | Source | Raw or derived? |
|-----------|-----------|--------|-----------------|
| *All filings* list | The stream of announcements | `nidp.corporate_announcements` | **Raw** (from exchange) |
| Filing's issuer, date, subject | Filing metadata | same table | **Raw** |
| **MATERIAL** sort | High-impact first | `impact_score` on the row | Derived (a score) |
| *"Read for you today"* cards | Today's top-3 shortlist | `/signals` over the same table | Derived (selection) |
| **AI summary** + **headline metric** in the drawer/panel | The readable gist | `nidp.corporate_event_signals` (an LLM read the PDF) | **Derived — check hardest** |
| **Page citations** in the insight panel | "this is on page N" | same signal JSON | Derived |
| Link to the **original PDF** | The actual filing | `nidp.documents.source_url` | **Raw — this is the source of truth** |
| **"In your portfolio"** badge | You hold this company | your holdings (`/portfolio-held`, Mongo) | Derived (a match) |

> **Why this matters for testing:** the raw fields you check against the exchange website;
> the *derived* fields you check against the **PDF's actual content**. The `source_url` /
> download button is your ground truth — the same document the exchange published.

---

## How to use it (feature tour)

1. **Read for you today** — the top row. Up to 3 cards the app thinks matter most *today*.
   Toggle **today ↔ latest**. Click a card → a **drawer** slides in with the AI summary
   and detail.
2. **"In your portfolio" badge** — if a filing is from a company you hold, a pill flags it
   on the card and in the drawer.
3. **Search a company** — type in the search box, pick a suggestion; the feed narrows to
   just that company (a scope chip appears; the "Read for you" row hides). Clear the chip
   to go back.
4. **Thematic starters** — pre-written prompts (tabs: **Curated / History / Favorites**).
   Click one to run it through the copilot.
5. **Ask bar** — ask a plain-English question ("who flagged margin pressure?"). The answer
   comes back with **source chips** you can click to the underlying filing.
6. **All filings** — the full list. Sort **MATERIAL** (impact-first) or **LATEST**
   (newest-first); filter with the facet chips.
7. **Expand a filing** — opens the **AI-insight panel**: summary, sections, and **page
   citations** into the PDF.
8. **Documents** — a per-company library; **download** opens the original filing PDF.
9. **Alerts** — pick which filing types/channels you'd want alerted on. *Note: delivery is
   intentionally switched OFF right now — saving the preference is the only expected
   behaviour.*

---

## The endpoints behind it (for API testing)

All under `/api/filings/` (`backend/routes/filings.py`):

| Endpoint | Serves |
|----------|--------|
| `GET /feed` | the *All filings* list (paging + facets + `symbol` scope) |
| `GET /signals?today_only=true` | *Read for you today* (top-3, IST-today) |
| `GET /portfolio-held` | the held names/symbols that drive the badge |
| `GET /{announcement_id}/insights` | the AI summary/metric/sections + `source_url` |
| `GET /companies/search` | the search type-ahead |
| `GET /companies/{symbol}/documents` | the per-company document library |
| `GET` / `PUT /alerts` | alert preferences (delivery off) |

---

## How to test it (the short version)

Two dimensions, always both — this is the house rule: **the app runs AND the data is real.**

1. **UI test** — does each feature above actually work? (loads, clicks, drawer opens, sort
   reorders, search scopes, download opens a PDF). Testable by hand or with the Playwright
   `data-testid`s already on every element.
2. **DATA / source-of-truth test** — the important half. Take a filing the app shows, open
   the **original BSE/NSE document** (the download link, and independently find it on
   bseindia.com / nseindia.com), and confirm:
   - raw fields (issuer, ticker, date, doc type) match the exchange, **and**
   - **derived fields are faithful** — the AI summary invents no numbers, the "headline
     metric" is actually stated in the PDF, and the page citation points to the right page.

   A filing that renders perfectly but whose summary contains a number that isn't in the
   PDF is a **data bug**, and catching it is the whole point.

3. **Cross-check** — hit the endpoint (e.g. `curl .../api/filings/signals?today_only=true`)
   and confirm it returns the same thing the screen showed. If UI and API disagree, that's
   a finding too.

👉 **Do it step-by-step** with the fill-in checklist:
[intern-research-app-validation-exercise.md](intern-research-app-validation-exercise.md).

---

### Two known quirks (so you don't mistake them for bugs — but still log them)

- Some announcements arrive **unclassified** (blank category/impact), so they sort to the
  bottom under MATERIAL. Expected today; note it if it looks wrong.
- A few **older BSE attachment links 404** (the exchange moves aged files). Note it and
  move on.
