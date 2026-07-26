# SURAKSHA — working prototype (v0.1)

A single-process, end-to-end demonstration that an examination paper can be made
**worthless to leak** and **traceable when leaked**.

Six candidates. Six different papers. Same difficulty. Sealed until the exam window opens
*and* the candidate's biometric matches. Leak one, and it names the leaker in milliseconds.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py          # -> http://127.0.0.1:8000
```

The exam window opens **60 seconds after startup** (the startup banner prints the exact
time), so you can demo the pre-window refusal before it opens. To skip the wait:

```bash
curl -X POST http://127.0.0.1:8000/api/admin/set_window \
     -H 'Content-Type: application/json' -d '{"minutes_from_now":0}'
```

Demo logins: `C1/finger1` (priya), `C2/finger2` (rohan), … `C6/finger6` (arjun).

---

## The 10-minute demo

| | Do this | What it proves |
|---|---|---|
| 1 | Open `/dashboard`. Every candidate's paper is `~2.2 kB sealed`, and `max pairwise Δ mean b = 0.0166 < 0.15`. | **Unique papers, equal difficulty.** Nobody can be advantaged or disadvantaged by which variant they drew. |
| 2 | Open `/terminal` **before** the window. Pick C1, enter `finger1`, "Get my paper". | `⛔ REFUSED_EARLY`. A correct biometric at the wrong time still gets nothing. The refusal is on the ledger. |
| 3 | Try C1 with `wrong-finger` after the window opens. | `⛔ REFUSED_AUTH`. Right time, wrong person — still nothing. |
| 4 | C1 + `finger1` after the window opens. | Key released, paper decrypts, watermark `CANDIDATE-C1` across the page. |
| 5 | Now C2 + `finger2`. | Visibly different questions, in a different order, with options in a different order. |
| 6 | As C2, click **"Copy paper text (simulate leak)"**. | This is Rohan walking out with the paper — as plain text, the hardest artifact to trace. |
| 7 | Paste it into `/dashboard` → Forensics → "Trace this leak". | `🎯 IDENTIFIED — C2 (rohan) · order match 10/10` in ~25 ms. Note the runner-up line: another candidate holds some of the same items but matched 0/10, because **the order is the watermark, not the items**. |
| 8 | Paste lorem ipsum, or a real paper with its questions shuffled. | `🚫 FABRICATED`. Rumour-kill: a claimed "leak" that matches no issued variant is provably fake. |
| 9 | "Verify chain" → intact. Then `python3 tamper_demo.py --keep`, verify again. | `✗ TAMPERED at row N`. Editing the audit trail behind the app's back is detected at the exact row. |

Then, for the punchline:

```bash
grep -c "CANDIDATE-C" suraksha.db    # 0 — no assembled paper exists in plaintext anywhere
```

---

## How it works

**Key service (simulated HSM).** `MASTER_KEY = os.urandom(32)` lives only in this process's
memory — never written, never returned by any endpoint. Each candidate's key is
`HKDF-SHA256(MASTER_KEY, info=candidate_id)`. Because the master key is ephemeral, papers are
re-sealed on every startup; assembly is seeded so the papers themselves are identical.

**Assembly.** For each candidate: shuffle the 60-item bank with a candidate-seeded RNG, take
10, then greedily swap items in/out until the variant's mean IRT difficulty `b` sits on 0.
All six variants land within ±0.015 — comfortably inside the ±0.15 tolerance.

**The watermark is the permutation.** After selection, the question order and each question's
option order are shuffled from `Random("watermark::{candidate_id}")`. That permutation *is*
the identifying mark: it survives copy-paste, retyping, and screenshots-then-OCR, because it
isn't a mark in the text — it's the text's arrangement. A visible `CANDIDATE-{id}` banner is
the second, deliberately obvious channel.

**At rest.** The whole assembled paper — stems, options, correct answers, and the watermark
permutation — is one AES-256-GCM ciphertext in `variants.ciphertext`, authenticated with the
candidate ID as AAD. Forensics has to go back through the key service to compare anything.

**Forensics.** For a pasted artifact, locate each variant's stems in the text, sort by
position to recover the order, and count positional matches against every sealed variant.
≥6 of 10 → identified; below that → `FABRICATED`. Option order is decoded per question as a
corroborating second channel.

**Ledger.** `hash = SHA256(prev_hash | ts | actor | action | detail)`. `/api/ledger/verify`
re-walks the chain and reports the first row whose content or link doesn't reconcile.

---

## Honest simplifications (this is a prototype, not a system)

- **Decryption is server-side, not in-browser.** The real design decrypts under WebCrypto in
  terminal memory. Here the server decrypts and sends the rendered paper over localhost HTTP.
  The zero-knowledge-ops boundary is therefore *demonstrated at the storage layer only*.
- **The master key is `os.urandom` in one process**, not an HSM, and not split across
  custodians. It dies with the process; papers are re-sealed on restart.
- **"Biometric" is a passphrase** presented through a fingerprint-styled field. No UIDAI, no
  sensor, no liveness.
- **The item bank is stored in plaintext.** `grep suraksha.db` *will* find question stems in
  the `items` table. That is the bank, which in the real design is a separately-controlled
  service. What never exists in plaintext at rest is any **assembled candidate paper** —
  which is the thing that's worth leaking.
- **No device attestation, no quorum/break-glass, no IRT scoring, no device-failover.**
  Scoring is a raw count, not an ability estimate. These were explicitly out of scope here;
  the PRD (`docs/SURAKSHA-prototype-PRD.md`) specifies them as FR-12/FR-21, FR-26, FR-29.
- **No authentication on the admin/dashboard routes.** Anyone who can reach the port can move
  the exam window.

## Files

| | |
|---|---|
| `app.py` | the entire backend — bank, assembly, key service, terminal API, forensics, ledger |
| `static/{index,terminal,dashboard}.html` | the three pages, vanilla HTML/JS |
| `TEST_CASES.md` | the 17 test cases, authored before the implementation |
| `acceptance.py` | runs T01–T16 against the live HTTP API — `python3 acceptance.py` |
| `e2e/suraksha.spec.ts` | T17, the three demos through the real UI — `npx playwright test` |
| `tamper_demo.py` | acceptance step 9 — edit the ledger behind the app's back |
