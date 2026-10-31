# OVERRIDE — F&O detail popup: a live walk against the real F&O routes

REASON: The popup reuses the desk's own F&O hooks and tables, which were exercised here only against mocked routes (synthetic fixture) in a production build; no staging deploy of this branch exists and
the Playwright session has no signed-in staging token. Needed to finish: after the merge and the frontend rebuild, sign in on staging, ask "Where is smart money moving?", open Details › on a long-buildup stock and check
(1) the option chain and range bar show that stock's own expiry, walls and PCR, (2) the futures tab lists its listed contracts with day change and OI change, (3) Open in Chart Analysis lands on Trade Desk › Chart
Analysis with that symbol selected and a paper trade can be started from there. Also: after the deploy, trigger the assistant's usage limit (or read the log) and check the chat shows the usage-limit sentence.

Not claimed anywhere: that the popup was seen with real F&O data in a browser; any order placement (nothing here can place, modify or cancel one).
