# Closing Bell — the nightly market-wrap video

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

1. **Preflight.** Requires 8 GB free on `/`, because deploys need 6 GB. Builds the tools image
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
