# Event Intelligence: show the AI's own one-line summary for filings the importance check judged routine: test cases

Ask (user, 2026-10-23): why is the AI summary not shown when results and other events are declared.
Verified cause (staging Mongo, read-only): the AI pipeline is running (23 Oct IST: 1,747 filings through the importance filter, 180 fully analysed, newest 21:29), but the filter keeps ~10%.
Of the 312 filings today whose filter title mentions results, revenue or profit, 231 were dropped as routine (scores 50-58; e.g. DCB Bank Q1 PAT +36%, SBI Life, Laurus Labs, Tata Consumer).
For a dropped filing the card's one-liner was "Assessed as routine (importance N/100): <why>", hiding the factual one-line the filter had written (its `title`) behind the verdict.
Fix (this repo): lead with the filter's factual title and keep the verdict visible after it. Not fixed here (the filter lives in the research pipeline, outside this repo): whether results declarations should always get the full analysis.

| ID | Scenario | Type | Expected |
|----|----------|------|----------|
| TC-1 | a dropped filing with a title: the one-liner is "<title> · Assessed as routine (importance N/100)"; sentiment stays neutral; it never reads important | pytest | text |
| TC-2 | a dropped filing with no title but a reason keeps the old wording | pytest | text |
| TC-3 | the Quick Summary section for a dropped filing lists the title and the reason (verdict in the heading) | pytest | sections |
| TC-4 | kept filings, full analyses, second-opinion override and the Mongo failure path are unchanged (existing tests) | pytest | pass |
