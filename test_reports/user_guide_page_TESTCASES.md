# User Guide page + homepage links — test cases (authored before implementation)

Owner asks, 5 Nov 2026: "Please provide the links in the homepage. A complete User Guide" and "Where user can choose
the preferred language and the video link changes".

Design:
- New public page `/user-guide` (marketing shell, no backend). Five languages (English, हिंदी, தமிழ், मराठी, ગુજરાતી).
  The language buttons switch the video, its captions, the direct video link and the share link; `?lang=` keeps the
  choice in the URL. The playback position carries over a language switch (every language shares one timeline).
- Chapters with times (seek on click) and the complete written guide in the chosen language (the narration, section by
  section, each with "Open in the app ›" where a screen exists).
- Videos and captions stay where they are published: `/downloads/promo/nivesh-copilot-da8691abbb/` (staging nginx).
  The written guide text is committed as `frontend-v5/public/user-guide/<lang>.json`.
- Homepage: a "User guide" header link, and a "Complete user guide" section with the same five language buttons;
  choosing one changes the section's Watch link (`/user-guide?lang=<code>`) and its direct video link.

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-1 | Homepage | Header "User guide" link | e2e | visible, real anchor `/v5/user-guide`, keyboard Enter opens the page |
| TC-2 | Homepage | Guide section default | e2e | 5 language buttons, English pressed; Watch → `/v5/user-guide`; direct link → `…-en.mp4` |
| TC-3 | Homepage | Choose each other language | e2e | button pressed; Watch → `/v5/user-guide?lang=<code>`; direct link → `…-<code>.mp4` |
| TC-4 | Homepage → page | Choose Tamil, click Watch | e2e | page opens with `?lang=ta`, Tamil pressed, Tamil video |
| TC-5 | Page | Default language | e2e | English pressed; video src `…-en.mp4`; captions track `…-en.vtt` (srclang en); poster set |
| TC-6 | Page | Switch to Marathi | e2e | URL `?lang=mr`; video `…-mr.mp4`; track `…-mr.vtt`; direct + share links updated; guide text `lang="mr"` in Devanagari |
| TC-7 | Page | Deep link / bad code | edge | `?lang=gu` opens Gujarati; `?lang=xx` falls back to English |
| TC-8 | Page | Chapters and section seek | e2e | 5 chapters with times; clicking a section time seeks the video to that second |
| TC-9 | Page | Position kept on language switch | e2e | at t≈20 s, switching language loads the new video at ≈20 s |
| TC-10 | Page | Complete written guide | e2e | every section (43) with its heading and text; English uses "P&L"/"F&O", not "P and L" |
| TC-11 | Page | Copy share link | e2e | clipboard gets `<origin>/v5/user-guide?lang=<code>` |
| TC-12 | Page | Disclaimer in the chosen language | e2e | en "not recommendations"/"not investment advice"; hi "सिफ़ारिशें नहीं"/"निवेश सलाह नहीं" (and ta/mr/gu phrases) |
| TC-13 | Page | Guide text fails to load | failure | video and language buttons still work; notice "written guide could not be loaded" |
| TC-14 | Both | Phone width 390 px | e2e | no horizontal scroll; language buttons wrap; homepage section visible (header links hide ≤ 920 px) |
| TC-15 | Page | Compliance copy | e2e | no "SEBI-aligned/compliant" claim; our own copy has no buy/sell/stop loss/target words |
| TC-16 | Staging files | The five videos, captions and poster the page points at | data (curl) | mp4 206 video/mp4 with range; vtt 200 text/vtt; poster 200 image/jpeg |
| TC-17 | Regression | Existing homepage / market-commentary / SEBI-claims specs | e2e | same results as on `origin/dev` (baseline run first) |
| TC-18 | Build | `tsc --noEmit` and `vite build` | build | clean |
