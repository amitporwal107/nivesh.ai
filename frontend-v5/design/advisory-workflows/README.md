# Advisory Workflows — V5 Screen Designs & Product Tour

High-fidelity design deliverables for the 7 advisory workflows (WF-01 … WF-07), rendered in the
real V5 design system (Instrument Serif / Inter Tight / JetBrains Mono, mint `#0E8A55`, the
`.nv-*` component kit). **Design mockups only** — sample data, not wired to live APIs.

## Files
| File | What it is |
|---|---|
| `screen-designs-v5.html` | The deliverable — **46 high-fidelity screens** across all 7 workflows, in-app V5 shell, with a light/dark toggle. |
| `screen-designs.html` | Wireframe/status overview — every screen tagged **Live / Extend / New** (from the FR audit) + shared foundations. |
| `tour.html` | Cinematic auto-playing **product tour** (intro → one scene per workflow using the real screens → outro), with player controls. |
| `nivesh-advisory-tour.mp4` | The tour rendered to video (1280×720, ~55s) for social / decks. |
| `kit/` | The **shared design library** everything is built from. |
| `screens/wf0*.html` | Per-workflow screen fragments (assembled into `screen-designs-v5.html`). |

## kit/ — shared library
| File | Role |
|---|---|
| `fonts.css` | The 3 V5 typefaces inlined as base64 (self-contained, no CDN). |
| `v5-kit.css` | Real V5 tokens (both themes) + `.nv-*` classes + shared screen furniture (shell, tables, forms, charts, states). |
| `KIT-GUIDE.md` | Authoring guide: class cheat-sheet, rules, and 2 worked example screens. |
| `assemble.py` | Stitches `fonts.css` + `v5-kit.css` + `screens/*.html` → `screen-designs-v5.html` (validates tags + self-containment). |
| `build_tour.py` | Generates `tour.html` from the real screens. |
| `record_tour.js` | Drives `tour.html` in headless Chromium (Playwright) → records the video. |

## Regenerate
```bash
python3 kit/assemble.py                        # rebuild the 46-screen catalogue
python3 kit/build_tour.py                       # rebuild the tour page
node    kit/record_tour.js                       # re-record the video (needs playwright + chromium)
ffmpeg -y -i video/*.webm -movflags +faststart -pix_fmt yuv420p -c:v libx264 -crf 20 out.mp4
```

Status colours (Live / Extend / New) reflect the implementation audit — they indicate how much
already exists to build on, not that a screen is production-complete.
