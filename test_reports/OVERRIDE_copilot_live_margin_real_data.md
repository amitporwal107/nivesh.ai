# OVERRIDE — F&O board: live premiums and a real Zerodha margin figure on real data

REASON: On 31 Oct 2026 (a Saturday) the market was closed and the platform's Kite login had expired, so no live option premium and no Zerodha margin figure could be
read from real Kite data; staging answered "Needs login" (verified on real data) and the logged-in paths are verified only on constructed inputs (FB-11, FB-16, FB-17, FB-18) and
fake Kite objects. Needed to finish: the admin's Kite login of the day and a trading session, then on staging read "Which F&O setups are attractive?" and check that (1) rows
show the Live badge for contracts that traded today and `mode` is "mixed", (2) the live max loss of a spread equals (premium paid − premium received) x lot size, (3) the margin
cell shows a figure and the notice is gone, (4) with the platform login absent but the user's own Zerodha connected, the margin comes from "your Zerodha account".

Not claimed anywhere: a live or margin figure from real data; any order placement (nothing here can place, modify or cancel one).
