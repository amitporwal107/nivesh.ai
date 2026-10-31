# F&O Lab Candidates view: test cases (authored before implementation)

Ask (user, 2026-10-23): build the F&O Lab candidate screen with research-status labels, from the approved design canvas
(https://claude.ai/artifact/Mz6SDFr16FCHTxqcuH2DCa, artboards Main and Mobile). Candidates are shown as descriptive observations ordered for review,
never as recommendations or "best trades". Data: GET /api/fno/scan/candidates (backend/routes/fno.py), already merged and read only.

Backend (the research block carries the real research record):
| ID | Scenario | Type | Expected |
|----|----------|------|----------|
| TC-1 | `research` block: status stays `research_setting_not_validated`; lists the two experiments with id, stage, finding, data window and date; names the lead experiment id; never `validated` | pytest | block |
| TC-2 | the other candidate-engine tests still pass (scores, coverage, no renormalisation) | pytest | pass |

Frontend (Playwright, mocked API, production build; fixtures in the shape of the real route):
| ID | Scenario | Type | Expected |
|----|----------|------|----------|
| TC-3 | a "Candidates" tab sits after "OI build-up" and before "NIFTY & BANKNIFTY"; opening it requests /api/fno/scan/candidates once | e2e | tab order, 1 request |
| TC-4 | research banner: "Research setting · not validated", both experiment ids, the data window, "not a recommendation" | e2e | text |
| TC-5 | category selector lists the four categories with candidate counts; the first category with candidates is selected; switching changes the cards | e2e | counts, cards |
| TC-6 | a card shows symbol, "#n of N", label chip, futures price change, OI change, cash change, expiry with days | e2e | values from the payload |
| TC-7 | signal strength and tradeability are separate bars with points / 100 and coverage; an incomplete candidate shows the Incomplete chip and the "not earned" input with its weight; strategy quality reads "Unavailable" | e2e | text, bar widths |
| TC-8 | the five confirmations show holds / does not / unknown from `checks`; fundamental context is labelled "not part of any score" | e2e | text |
| TC-9 | "Open <SYM> chain" switches to the chain view with that symbol loaded | e2e | data-symbol |
| TC-10 | the not-ranked list is collapsed and shows each reason | e2e | text |
| TC-11 | banned wording: the screen never says "best trade", "top pick", "buy now", "sell now", "recommended" | e2e | absent |
| TC-12 | a 502 from the route shows the Lab's problem notice with a retry; no cards; the Lab stays usable | e2e | notice |
| TC-13 | 390px: no sideways overflow of the page or the shell scroller | e2e | 0 |
| TC-14 | typecheck passes (`tsc --noEmit`) | tsc | exit 0 |
