# Functionality Verification Report — Closing Bell, published every trading day

- **Branch:** feat/closing-bell-daily (from origin/dev, after PR #389)
- **Date:** 2026-10-28
- **Author:** Claude (Full-Stack Developer + Design Engineer + QA)
- **Environment:** staging app VM (backend container, NIDP DaaS, desk APIs as the bot); frontend-v5 production build in the Playwright container
- **Changed areas:** backend scripts: yes (`backend/scripts/closing_bell.py`, run by cron, no route) · frontend src: yes · ops: cron, installer, nginx types

## Summary
The owner asked for the Closing Bell video to be published every trading day after the close, once the snapshots
refresh (decisions: auto-publish when every check passes, read-only bot account for the desk footage, template
script, wait for the 22:45 Top 10 list). `tools/closing_bell/pipeline.py` runs from cron every 10 minutes
22:00–00:50 IST Mon–Fri. When the NIDP snapshot and the day's Top 10 list are ready, it collects the day's data
(DaaS, desk GETs as the bot, Sensibull, Trendlyne), writes the script from templates with every number traced,
checks it, narrates it, renders the cards, records the desk read-only, assembles and checks the video, and
publishes to `/downloads/closing-bell/<date>/` with an `index.json`. The new public page `/v5/market-commentary`
(latest + archive) and the homepage link and card read that index. If any check fails, the edition is held and
the operator is alerted.

Order of work, stated plainly: the backend helper and the build tools were written and exercised against
27 Oct data first. These test cases were written after that, before the frontend tests and the homepage
change were finished.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | Readiness | `ready` for a finished day (27 Oct) and an unfinished one (28 Oct, morning) | api (staging) | 27 → ready true, exit 0; 28 → ready false, exit 3 | PASS |
| TC-2 | Bot account | `ensure-bot`, `session`, `revoke` on staging | api (staging) | role `user`, onboarded; session authenticates a desk GET; revoked token gets 401 | PASS |
| TC-3 | Collect | `collect --date 2026-10-27` | api (staging) | bundle has 10 indices, 4 heatmaps (≥450 priced in N500), sector returns, results week, Top 10 list, FII/DII for 27 Oct | PASS |
| TC-4 | Cards | cards from the 27 Oct bundle | unit | N50 25/25, N500 356/138, FII +4,240.39 / DII −1,250.03, MTD −48,688.5 / +60,469.9, biggest since 2026-09-02, leading IT/Telecom/Consumer Services | PASS |
| TC-5 | Script trace | every number in narration + captions is traced and still equals its source | unit | checks `ok`, 0 untraced | PASS |
| TC-6 | Script gate (negative) | one number altered (4,240 → 4,420) | unit | checks fail, names the untraced number | PASS |
| TC-7 | Data gate (negative) | heatmap missing / Top 10 list missing | unit | data_fails non-empty → edition held | PASS |
| TC-8 | Wording gate | narration has the ideas and closing disclaimers; "picks"/"target price" rejected | unit | pass on real script; fail when "picks" inserted | PASS |
| TC-9 | Scheduling logic | before-noon runs map to the previous evening; cut-off 00:50 | unit | edition_date / past_cutoff as specified | PASS |
| TC-10 | Publish | publish twice + retention | unit | files in `<date>/`, index newest-first, re-publish replaces, older than N removed from list and disk | PASS |
| TC-11 | End-to-end dry run | `pipeline.py --date 2026-10-27 --force --dry-run` on staging | e2e (staging) | exit 0, script + media checks pass, recorder reaches all 7 screens, 1920×1080, audio, loudness in band | PASS |
| TC-12 | Page — latest | `/v5/market-commentary` with an index of 2 editions | e2e | newest edition: title, video poster/src/captions, headlines, disclaimer, transcript sections + cues, archive lists the other | PASS |
| TC-13 | Page — by date / archive | archive link and direct `/v5/market-commentary/<date>` | e2e | that edition shown; unknown date → "No edition" notice with link to latest | PASS |
| TC-14 | Page — empty / error | index.json 404 / HTTP 500 | e2e | empty notice / error notice; no fake data | PASS |
| TC-15 | Real media | the built 27 Oct web.mp4 served through the page | e2e (media) | duration ≈ 351 s, audio decoded | PASS |
| TC-16 | Homepage | header link → `/v5/market-commentary`; "Closing Bell" card shows the latest edition and opens it; hidden when no editions | e2e | as stated, desktop + 390 px phone (no sideways scroll) | PASS |
| TC-17 | Regression | existing homepage / blog / blog-research-tour specs | e2e | no new failures against the origin/dev baseline | PASS |
| TC-18 | Build | `tsc --noEmit`, `vite build`, `py_compile`, nginx `-t` | build | clean | PASS |

## Results (real output, this session)

### Backend on staging (TC-1, TC-2, TC-3)
Run inside `nivesh-staging-app-backend` with an un-merged copy of the script (`/tmp/closing_bell.py`; the
deployed checkout was not touched):
```
ready --date 2026-10-27 -> {"date": "2026-10-27", "ready": true, "snapshot_ready": true, "ideas_list": true, "snapshot_built_at": "2026-10-27T16:30:02.207125+00:00"}   exit 0
ready --date 2026-10-28 -> {"date": "2026-10-28", "ready": false, "snapshot_ready": false, "ideas_list": false, "snapshot_built_at": null}   exit(28) 3
ensure-bot -> {"user_id": "closing-bell-bot", "role": "user", "onboarding_completed": true}
desk GET with bot session: HTTP 200
me: {'user_id': 'closing-bell-bot', 'role': 'user', 'is_admin': False, 'onboarding_completed': True}
{"revoked": 1}
desk GET after revoke: HTTP 401
collect --date 2026-10-27 -> indices list 10 · heatmap n500 stocks 501 (as_of 2026-10-27) · sensibull days 82 (27 Oct FII buy_sell_difference 4240.39)
                             · ideas 2026-10-27 [COFORGE, ICICIBANK, SAGILITY, ...] · macro months ['2026-10', '2026-11']
```
The bot session token was written only to a 0600 file and never printed.

### Unit tests (TC-4 – TC-10)
`python3 -m unittest discover -s tools/closing_bell/tests -v` → `Ran 18 tests ... OK`. These cover:
- the 27 Oct figures: 25/25, 356/138, +4,240.39 / −1,250.03, MTD −48,688.5 / +60,469.9, biggest since 2026-09-02, leading IT / Telecom / Consumer Services;
- every number traced: `numbers_checked` 183, 0 untraced;
- an altered number (4,420) is caught;
- a source value that changed after the script was written is caught (`trace mismatch fii.fii_net`);
- a missing heatmap and a missing Top 10 list each hold the edition;
- "picks" in the narration is rejected, and so is a missing closing disclaimer;
- the 00:50 cut-off and the before-noon edition-date rule;
- publish retention and re-publish (replaces the edition, no duplicate).

`pytest tests/test_closing_bell_script.py` in `nivesh/backend:staging` → `6 passed`. It covers ready, no Top 10 list, a stale snapshot, a holiday, a weekend, and the Sensibull month-name parameter.

### End-to-end dry run on staging (TC-11)
`sudo python3 tools/closing_bell/pipeline.py --date 2026-10-27 --force --dry-run --keep-work`. It used a
scratch root and destination: nothing was published and no alert was sent.
```
06:22:46 START 2026-10-27 · 06:22:46 building tools image · 06:23:22 fetching music bed (Wikimedia Commons, CC BY 3.0)
06:23:34 collect · 06:23:54 script checks ok: 183 numbers · 06:24:44 graphics · 06:27:12 recording desk footage
06:33:54 bot session revoked: {"revoked": 1} · 06:34:33 assembling segments · 06:40:08 DRY RUN ok in 1042s
media.json {"duration": 351.112, "size": 20066341, "width": 1920, "height": 1080, "has_audio": true, "lufs": -15.9, "timeline_total": 351.0}
checks_media.json {"ok": true, "fails": []}
recorder: s1 378 · s2 700 · s3 490 · s4 656 · s5 364 · s6 914 · s7 209 frames; warm_error None for all seven desk screens
```
- **Recorder misses:** two sector headers were off-screen (s4: Textiles, Construction Materials). Fixed after the run by scrolling to them first.
- **Frames:** a contact sheet of 8 frames was reviewed. It showed the title, the scoreboard card, results with the OneSource search on the desk, the Nifty 100 movers, the Nifty 500 sector card, the Top 10 ideas and the end card. All dates come from the data.

### Frontend (TC-12 – TC-18)
Production build of the branch and of origin/dev, served by `vite preview` (base `/v5/`); the served bundle
was confirmed before each run (`serving assets/index-C9nE4jto.js` vs `index-gqiPS-id.js`).
- `npx tsc --noEmit -p tsconfig.json` → `tsc exit 0`; `npx vite build` → `vite build (branch) exit 0`, `✓ built in 23.04s`.
- New spec `homepage-market-commentary-daily.spec.ts` (TC-15 uses the real built 27 Oct mp4, poster and captions):
```
✓ TC-12 latest edition: title, player, headlines, disclaimer, transcript, archive (2.0s)
✓ TC-13 archive link and direct date URL open that edition; unknown date says so (4.4s)
✓ TC-14 no editions yet → empty notice; feed error → error notice; no sample data (2.6s)
✓ TC-15 the real built edition plays: about 351 s with audio (1.8s)
✓ TC-16 homepage: header link goes to the page; Closing Bell card opens the latest edition (3.1s)
✓ TC-16 homepage hides the Closing Bell card when nothing is published (863ms)
✓ TC-16 phone: the homepage card is the way in; page fits without sideways scroll (1.7s)
```
- **Regression (TC-17):**
  - **Branch run:** `42 passed / 5 failed`, plus `blog-research-tour` `10 passed`.
  - **Baseline on origin/dev:** `33 passed / 7 failed`.
  - **The 5 branch failures** also fail on dev, so this change did not cause them:
    - blog-unauth TC-1 and TC-2 (a stale "newest card");
    - three homepage.spec duplicate-button strict-mode tests.
  - **The 2 extra baseline failures** are this branch's updated `homepage-market-commentary` TC-1/TC-2. They now expect `/v5/market-commentary`, so on the dev build they fail as they should.
- **nginx configs (TC-18):**
  - Edge config: `nginx -t` → `syntax is ok` / `test is successful`. It serves mp4 / vtt / json / jpg under `/downloads/` with real types.
  - v5 frontend config: tested in a throwaway nginx:
    - `/v5/x.vtt` → `200 Content-Type: text/vtt`;
    - `/v5/blog/x` → `200 text/html` (the app still loads);
    - `/v5/missing.vtt` → `404`.
  - The caption fix matters because live staging currently serves `/v5/closing-bell-27oct2026.en.vtt` as `application/octet-stream`.
- `py_compile` of every tool and the backend script → `py_compile OK`.

## Data correctness
- **27 Oct data:** the cards match the figures cross-checked by hand on 27 Oct. Those were all 494 Nifty 500 moves against the desk heatmap, and Sensibull's 26 Oct figures against the warehouse NSE row.
- **Publish gate:** a number reaches the page only if its trace matches the source.
- **After-the-bell list:** the desk's own `filed_after_close` flag shows that on 27 Oct only L&T, among F&O names, filed after the close. The hand-made 27 Oct video's list of after-the-bell names was looser (Bajaj Auto 15:21 IST, Maruti 15:27 IST and Cipla 13:31 IST filed during the session). The automated rule follows the desk.

## Not verified / needs the owner
- **Live on staging:** UNVERIFIED until the PR is merged and these steps are done:
  - **nginx:** the edge container must be restarted, because the config file is a single-file bind and a merge does not reload it. Check `md5sum` of the host file vs the container copy.
  - **Frontend image:** must rebuild (auto-deploy).
  - **Cron:** install it with `install-closing-bell.sh`.
  - **First edition:** the 28 Oct evening run. Check its state file, the page and the video.
- **Trendlyne:** the staging `TRENDLYNE_MCP_URL` returns HTTP 403 (its fingerprint differs from the working host copy). After-the-bell profits will use the desk's own figures until the owner updates it.
- **Alerts:** the email path is not exercised live, because it would email the operator. The code path is the same as the Kite token alert. On staging only `KITE_TOKEN_ALERT_EMAIL_TO` is set: there is no NIDP SMTP and no Telegram.

## Inputs required from user
- Merge approval for the PR, and approval to restart the edge nginx container.
- An updated staging `TRENDLYNE_MCP_URL`, or explicit OK for me to write it.

---

## Update 2026-10-28 (later): louder anchor voice + five languages

The owner asked for two more things the same morning: "make the video anchor voice … loud", and "publish the
video commentary in Hindi, Tamil, Marathi, Gujarati". The decisions:
- fixed translated templates, no night-time machine translation;
- voice, subtitles and transcript in each language, with the cards in English;
- all four languages live with the merge;
- the viewer can switch language, and the transcript follows.

### Test cases (added before the language code was finished)
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-24 | Mix | louder voice: voice compressed, bed lower and ducked harder, −14 LUFS target | media | speech louder, music ≥ 15 dB under the voice, media check passes | PASS |
| TC-25 | Script | every beat rendered in en/hi/ta/mr/gu, no unfilled template, Indic text never says "percent" | unit | true for 27 Oct | PASS |
| TC-26 | Script gate | numbers + both disclaimers checked in every language; an altered Hindi number and a missing Tamil disclaimer are caught | unit | fails named per language | PASS |
| TC-27 | Branches | a falling market with FII selling renders and passes in every language | unit | ok | PASS |
| TC-28 | Dates/times | localized: 2 सितंबर / செப்டம்பர் 2 / शाम 4 बजे / இரவு 11:30 மணிக்கு / बुधवार | unit | as stated | PASS |
| TC-29 | Publish | all languages published; older editions keep English only after N | unit | as stated | PASS |
| TC-30 | End-to-end | 5-language dry run of 27 Oct on staging | e2e (staging) | every language's video is the right length, has audio, −14 LUFS; checks pass | PASS |
| TC-31 | Page | switcher lists five languages, English default; each switch swaps video, captions (srclang), transcript (lang attr) and disclaimer; `?lang=` deep link; unknown → English; old edition → no switcher | e2e | as stated | PASS |
| TC-32 | Real media | the built Hindi video plays with audio | e2e (media) | duration ≈ published, audio decoded | PASS |

### Evidence (real output)
- **Mix, 27 Oct remix of the live video** (`ebur128` windows):
  - speech went from `old mix -15.7 LUFS` to `new mix -14.1 LUFS`;
  - while the anchor talks, the stems measure `voice -17.3, music -33.8`, so the music is 16.6 dB below the voice;
  - pipeline dry run with the new mix: `"lufs": -14.1`, `checks_media {"ok": true, "fails": []}`.
- **Unit tests:** `python3 -m unittest discover -s tools/closing_bell/tests` → `Ran 25 tests ... OK`.
- **Script check on 27 Oct, five languages:** `{"ok": true, "numbers_checked": 475, "fails": [], "data_fails": []}`.
- **Voice fitting** (`tts/fit.json`):
  - at normal pace the narrations measure en 327.2 s, hi 422.2, ta 408.5, mr 426.8 and gu 405.9;
  - after fitting the maximum rates were hi +25%, ta +28%, mr +25% and gu +25%, with no beat over its slot by more than 3%.
- **5-language dry run** (`pipeline.py --date 2026-10-27 --force --dry-run`):
```
08:03:39 script checks ok: 469 numbers · 08:05:29 graphics · 08:07:49 recording desk footage
08:16:10 assembling segments · 08:22:32 language tracks: hi, ta, mr, gu · 08:23:47 DRY RUN ok in 1221s
checks_media {"ok": true, "fails": []}
media_{hi,ta,mr,gu}: duration 400.04 s, 1920x1080, has_audio true, lufs -14.1, timeline_total 400.0
```
- **Bot session during this run:** the backend container restarted at 08:06 IST in the middle of the run. That removed the
  un-merged `/tmp` test copy of the script, so the revoke step failed and one bot session was left in Mongo. It was
  deleted by hand (`deleted bot sessions: 1 | remaining: 0`). `pipeline.py` now logs a failed revoke as a WARNING;
  before, the line was blank. Merged code lives in the bind-mounted repo, so a restart does not remove it. The
  session would also expire by itself after 75 minutes.
- **Playwright** (production build, served bundle confirmed: `serving assets/index-RmKK5Vv2.js`):
```
✓ TC-19 switcher lists the five languages; English is the default
✓ TC-20 [hi] / [ta] / [mr] / [gu] switching swaps the video, captions, transcript and disclaimer
✓ TC-21 a shared link opens in its language; an unknown ?lang falls back to English
✓ TC-22 an edition published before the languages is English only, without a switcher
✓ TC-23 [hi] the real Hindi edition plays with audio
✓ TC-12..TC-16 (page, archive, empty/error, real English media, homepage, phone)
  5 failed (the same pre-existing dev failures: blog-unauth TC-1/TC-2, homepage.spec x3) · 50 passed · blog-research-tour 10 passed
```
  The first run of TC-13 and TC-22 failed because of the test's own file router: it threw ENOENT for the synthetic 26 Oct
  edition, which has no media file. It now returns 404 for missing files, and the rerun is above.
- **Visual check:** screenshots reviewed:
  - Hindi page at 1280 px: five-language switcher, हिंदी selected;
  - Tamil transcript at 390 px: Tamil section headings, no sideways scroll.

### Not verified / needs the owner
- **Wording review:** the Tamil, Marathi and Gujarati wording has not been reviewed by a native speaker; the templates are in `tools/closing_bell/i18n.py`.
- **Listening check:** the Indian-language voices were not listened to end to end.

## Verdict: PASS
