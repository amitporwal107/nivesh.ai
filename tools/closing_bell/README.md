# Closing Bell and Opening Bell — the market videos

Two shows come out of this folder: the nightly **Closing Bell** (below) and, from 3 Nov 2026, the morning
**Opening Bell** (see [Opening Bell](#opening-bell-the-morning-edition)).

## Closing Bell — the nightly market-wrap video

Every trading day after the close, this folder builds a 5–7 minute "Closing Bell" bulletin from the Smart
Trading Desk and publishes it to the public page `/v5/market-commentary`. That page and the homepage
card read `/downloads/closing-bell/index.json`.

It has one male anchor in each of five languages, data cards beside read-only desk footage, a ticker,
captions, and a music bed ("The Complex", Kevin MacLeod, CC BY 3.0, credited on the end card).

## Languages

The page has a language switcher, and links like `?lang=hi` open straight into that language. Each
language has its own male voice:

| Language | Voice |
|---|---|
| English | `en-US-AndrewMultilingualNeural` |
| Hindi | `hi-IN-MadhurNeural` |
| Tamil | `ta-IN-ValluvarNeural` |
| Marathi | `mr-IN-ManoharNeural` |
| Gujarati | `gu-IN-NiranjanNeural` |

- **What's translated:** the voice, captions and transcript are in each language. The data cards and
  caption strip stay in English: they're mostly numbers and company names.
- **How the scripts are written:** every sentence pattern is translated once in `i18n.py`. Each night
  only the numbers, names and dates change: there is no machine translation at night. Numbers and the
  two disclaimers are checked in every language before publishing.
- **Review:** the Tamil, Marathi and Gujarati wording should get one native-speaker review. Edit
  `i18n.py` to change it.
- **Timing:** every language shares one picture and one timeline. Indian-language narration runs about
  25–30% longer than English, so it is spoken up to 20% faster than its normal pace. English slows a
  little, never below normal speed, to fill the shared slot.
- **Disk:** non-English videos (about 20 MB each) are kept for the newest 15 editions. English is kept
  for 45.

## When it runs

`deploy/nivesh-staging/closing-bell.cron` runs every 10 minutes, 22:00–00:50 IST, Mon–Fri. Each run exits
at once unless both of these are true:

- the NIDP EOD snapshot for the date has that day's prices and index closes (22:00 `snapshot_builder`);
- the day's Top 10 list is stored (22:45 ai-watchlist).

A build takes about 18 minutes, so editions usually publish around 23:15–23:30 IST. Runs before noon
belong to the previous evening.

| Outcome | State file `/opt/nivesh-staging/closing-bell/state/<date>.*` | Alert |
|---|---|---|
| every check passed | `published` | none |
| a check failed | `held` (nothing published) | yes |
| a step crashed | `failed` (one automatic retry first) | yes, after the retry |
| not ready by 00:50 | `missed` | yes |
| weekend / NSE holiday | `no_session` | none |

Every outcome is also written to Mongo `closing_bell_runs`.

Alerts go through the repo's operator channels: NIDP SMTP and Telegram. If neither is configured, they
use the app mailer, sending to `CLOSING_BELL_ALERT_EMAIL_TO`, or `KITE_TOKEN_ALERT_EMAIL_TO` if that is
unset.

## Steps (`pipeline.py`)

1. **Preflight.** Requires 8 GB free on `/`, because deploys need 6 GB (`CB_MIN_FREE_GB` lowers it, never below 7:
   a build peaks at about 1 GB). After publishing, `trim_work` keeps only the work folder's JSON, captions and
   transcripts; the published copies are the record. Builds the tools image
   (`Dockerfile`) if it is missing. Fetches the music once and checks its pinned sha256.
2. **Bot session.** `backend/scripts/closing_bell.py` sets up the bot. The bot is a read-only `user`-role
   account, `closing-bell-bot`. The job creates a 75-minute session for it and revokes the session at the
   end. The token only ever lives in a 0600 file.
3. **Collect.** Gathers, as one JSON bundle:
   - from NIDP DaaS: index EOD, snapshot, macro calendar;
   - from the desk's own GET endpoints, called as the bot: results week, Top 10, sector returns, heatmaps,
     smart-money flows, regime;
   - Sensibull daily FII/DII;
   - Trendlyne net profit for after-the-bell filers.
4. **`cards.py`.** Computes every figure the graphics and script use from the bundle.
5. **`script_gen.py`.** Fixed templates fill in the numbers. Every number goes through `Facts.n()`, which
   records where it came from. The wording is chosen per date, so the same date always gets the same text.
6. **`checks.py script`.** The edition is held if any of these fail:
   - **data:** index closes, all four heatmaps, sector returns and the Top 10 list are present;
   - **numbers:** every number in the narration and captions is traced and still equals its source;
   - **wording:** the disclaimers are present, and "picks" or "target price" never appear.
7. **Voice, graphics, footage.**
   - `synth.py`: the narration in every language, fitted to shared slots.
   - `build.py timeline`: timing for each line (the longest language sets each slot).
   - `gfx.py` with `gfx.html`: the cards.
   - `rec.py`: records the desk read-only. It navigates, hovers, scrolls, types in the Results-week search
     box and switches views. It never trades, saves or alerts.
8. **Assembly.** `build.py footage | seg | final | lang <code> | transcript` assembles the English video,
   then writes `out/web.mp4` (about 20 MB) and the poster. Each other language reuses the same picture
   with its own narration in `out/web_<lang>.mp4`. Captions and transcripts are written per language.
9. **`checks.py media`.** Checks length against the timeline, the audio track, 1920×1080 and loudness. It
   also checks that every desk screen loaded and that no login redirect happened.
10. **`publish.py`.** Writes `/opt/nivesh-staging/downloads/closing-bell/<date>/` and replaces `index.json`
    atomically. The newest 45 editions are kept, about 1 GB.

## Manual runs (root, on the app VM)

```bash
# build and check any date without publishing (output in /opt/nivesh-staging/closing-bell/work/<date>/out/)
sudo python3 /opt/nivesh-staging/repo/tools/closing_bell/pipeline.py --date 2026-10-27 --force --dry-run --keep-work
# re-publish a date (ignores the state file)
sudo python3 /opt/nivesh-staging/repo/tools/closing_bell/pipeline.py --date 2026-10-27 --force
# unit tests (no network)
python3 -m unittest discover -s tools/closing_bell/tests -v
```

Install or uninstall the schedule with
`sudo bash /opt/nivesh-staging/repo/deploy/nivesh-staging/install-closing-bell.sh [--uninstall]`.

## Known limits

- **Trendlyne.** If the staging `TRENDLYNE_MCP_URL` is rejected (HTTP 403, as on 2026-10-28), the
  after-the-bell profit changes fall back to the desk's own year-on-year figures, and the card says which
  source was used.
- **FII/DII timing.** If Sensibull has not published the day's provisional FII/DII figures yet, the
  bulletin uses and names the latest date it has.
- **Voice.** The voice is Microsoft Edge's online read-aloud service (edge-tts). It needs internet access
  at build time.

## Opening Bell (the morning edition)

The owner asked on 2 Nov 2026 for an opening-bell commentary "just like the closing one", with "anticipated moves today".
Their decisions:

- publish at about 9:10 IST, after the 9:00–9:08 pre-open;
- "anticipated moves" means data-based ranges and levels, never calls;
- no global cues for now (GIFT Nifty, US/Asia indices and USD/INR are not in the TrueData plan).

Same five languages, voices, checks and music as the evening. Editions go to
`/opt/nivesh-staging/downloads/opening-bell/<date>/` (served at `/downloads/opening-bell/`, its own `index.json`); the
page shows them at `/v5/market-commentary?show=opening` and the homepage has an Opening Bell card.

### What it says, and where each number comes from

| Segment | Content | Source |
|---|---|---|
| Headlines | pre-open indication, the range, the AI list's leaders, expiry / results today | as below |
| Previous session | Nifty 50 close, Bank Nifty / Midcap / Smallcap, FII/DII, MCX crude and gold | NIDP index EOD; Sensibull; TrueData `CRUDEOIL-I` / `GOLD-I` end-of-day bars |
| Pre-open | indicated Nifty, F&O advances/declines, biggest gap-ups and gap-downs, after-the-bell filers and AI-list names in the pre-open | NSE public pre-open (`/api/market-data-pre-open?key=FO` and `ALL`) |
| Ranges & levels | India VIX one-day range; largest put / call open interest; put-call ratio; max pain; on expiry day the ATM straddle; implied moves for F&O names reporting today | NIDP DaaS `/fno/<symbol>/chain` (NSE bhavcopy), India VIX close |
| Top 10 AI ideas | the evening's stored list, idea by idea, and the F&O board | desk `/api/desk/ai-watchlist` (the previous session's list) |
| Today | macro releases, results due (F&O), sign-off and disclaimer | desk macro calendar, Results Week for today |

How the figures are worked out (`cards_open.py`):

- **Range:** previous close × India VIX ÷ 100 ÷ √365, either way: one standard deviation, since VIX is annualised over
  calendar days.
- **Support / resistance:** the strike with the largest put open interest at or below spot, and the largest call open
  interest at or above spot, in the nearest expiry. On 2 Nov these matched the desk's own NIFTY card exactly
  (put wall, call wall, put-call ratio, max pain and the straddle; see `test_reports/opening_bell_20261102.md`).
- **Max pain:** the strike where option holders as a group would be paid the least at expiry.
- **Implied move:** at-the-money straddle ÷ spot, to the nearest expiry, for up to three F&O names reporting today.
- **Indicated Nifty:** previous close × the weighted ratio of each constituent's pre-open equilibrium price to its
  previous close, using the desk heatmap's index weights. It needs at least 45 of the 50 stocks priced; under ±0.10%
  it is read as a flat start. On the 27 Oct fixture the same weights reproduced the day's Nifty move to within 0.08
  percentage points (+0.06% worked out vs −0.02% actual).

Every number is traced (`Facts`) like the evening's, and the morning script must also say "not forecasts" (or its
translation) in every language.

### When it runs: two phases

| Phase | When (IST, Mon–Fri) | What |
|---|---|---|
| A | every 10 min, 06:30–08:50 | waits for the previous session's snapshot, Top 10 list and Nifty option chain; builds the script without the pre-open, all voices, graphics, desk footage (as the bot) and every segment except the cold open and the pre-open |
| B | 09:08 once | fetches the pre-open (polls NSE until its timestamp shows today at or after 09:08, until 09:12), re-scripts, re-voices and re-renders only the cold open and the pre-open segment, lays the ticker and each language's audio over the whole programme, checks, publishes |

Phase B takes about 5–6 minutes, so editions publish at about 9:14. The segment list is the same in both phases: in
phase A the pre-open segment is a one-line placeholder with 95 s of desk footage recorded, which phase B cuts to length.

State: `/opt/nivesh-staging/closing-bell/opening/state/<date>.{phase_a,published,held,failed,missed,no_session}`; the run
record is in Mongo `closing_bell_runs` with `kind: "opening"`.

| Outcome | Alert |
|---|---|
| published | none |
| held (a check failed, including a stale or missing pre-open) | yes |
| failed (phase A retries once on the next tick; phase B does not retry) | yes |
| missed (previous session's data not ready by 08:50, or phase A not done by 09:08) | yes |

### Manual runs

```bash
# dry run for a morning, using an earlier day's pre-open (TESTS ONLY; never publishes)
sudo CB_ROOT_OPEN=/tmp/ob-dry python3 tools/closing_bell/pipeline.py --kind opening --phase both --date 2026-11-03 --allow-stale-preopen --dry-run --keep-work
# the real thing, by phase
sudo python3 /opt/nivesh-staging/repo/tools/closing_bell/pipeline.py --kind opening --phase A
sudo python3 /opt/nivesh-staging/repo/tools/closing_bell/pipeline.py --kind opening --phase B
```

### Known limits

- No global cues (GIFT Nifty, US and Asian indices, USD/INR): not in the TrueData plan. The owner will ask TrueData
  about NSE IX and the currency segment.
- NSE's pre-open API gives no index-level row (`key=NIFTY` returns "No Data Found"), so the indicated Nifty is worked
  out from its constituents (above).
- The OI panel on the desk lists strikes near the money only; when a level is outside it, the recorder points at the
  nearest strike shown and logs it.
