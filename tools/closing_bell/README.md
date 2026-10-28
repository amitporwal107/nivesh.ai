# Closing Bell — the nightly market-wrap video

Every trading day after the close, this folder builds a 5–7 minute "Closing Bell" bulletin from the Smart
Trading Desk and publishes it to the public page `/v5/market-commentary`. That page and the homepage
card read `/downloads/closing-bell/index.json`.

It has one male anchor (edge-tts `en-US-AndrewMultilingualNeural`, +8%), data cards beside read-only desk
footage, a ticker, captions, and a music bed ("The Complex", Kevin MacLeod, CC BY 3.0, credited on the
end card).

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
   - `synth.py`: the narration.
   - `build.py timeline`: timing for each line.
   - `gfx.py` with `gfx.html`: the cards.
   - `rec.py`: records the desk read-only. It navigates, hovers, scrolls, types in the Results-week search
     box and switches views. It never trades, saves or alerts.
8. **Assembly.** `build.py footage | seg | final | transcript` assembles the video, then writes
   `out/web.mp4` (about 20 MB), the poster, captions and transcript.
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
