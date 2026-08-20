# Functionality Verification Report — FLOW LEDGER S3, net FPI direction on deal lists

- **Branch:** feat/flow-ledger-s3
- **Date:** 2026-08-19
- **Author:** Claude (full-stack-developer + domain-expert-analyst + qa-engineer)
- **Environment:** staging (nidp_staging)
- **Changed areas:** backend services: **yes** (`daas_api/flow_ledger.py`, `routers/flow_ledger.py`) · frontend src: no

## Summary — I was wrong, and this corrects it

I previously told the user S3 was structurally unfillable, on the grounds that "of
4,137 bulk deals in the last 90 days only 10 identify as foreign". That claim was
wrong twice over:

1. **It ranked counterparties by DEAL COUNT.** High-frequency domestic desks dominate
   that ranking by construction — they place thousands of small trades and net to
   roughly nothing. The stream asks for direction *by value*.
2. **It matched "foreign" with a narrow geography regex** (`MAURITIUS|SINGAPORE|…`),
   which misses most real FPI names.

Ranked by value, named FPI portfolio investors are plainly present:

```
FMRC FIDELITY ADVISOR INTERNATIONAL CAPITAL APPRECIATION FUND   ₹2,488 cr
SMALLCAP WORLD FUND INC                                         ₹1,393 cr
NOMURA INDIA INVESTMENT FUND MOTHER FUND                          ₹478 cr
BOFA SECURITIES EUROPE SA                                         ₹473 cr
SOCIETE GENERALE                                                  ₹461 cr
CITIGROUP GLOBAL MARKETS SINGAPORE PTE LIMITED                    ₹435 cr
GOLDMAN SACHS BANK EUROPE SE                                      ₹371 cr
MORGAN STANLEY ASIA SINGAPORE PTE                                 ₹247 cr
GOVERNMENT OF SINGAPORE                                            ₹74 cr
```

S3 is now filled from them, and RELIANCE moves from 70/100 to **90/100**.

## The three populations, and why only one scores

The deal lists carry three kinds of counterparty and only one is this stream's subject:

| population | examples | counted? |
|---|---|---|
| FPI portfolio investors | GQG Partners EM Equity, Fidelity Advisor Intl, Smallcap World, Nomura India, Goldman Sachs Bank Europe | **yes** |
| Foreign strategic / PE | Bayer AG, Mylan Inc, Twin Star (Vedanta holdco), BC Investments IV (Baring), Eight Roads Mauritius | no |
| Domestic prop / HFT | QE Securities, HRTI, Junomoneta, Graviton, iRage, Microcurves | no |

Population 2 is the subtle one. Those entities are foreign **and SEBI-registered as
FPIs**, so an offshore-name heuristic counts them — but a promoter or PE block exit is
not portfolio flow, and scoring it as "heavy FII selling" reads a one-off structural
trade as a distribution pattern. That is why the classifier is a curated whitelist:
Bayer AG and GQG Partners are both foreign, and no name-shape rule separates them.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | unit | 10 real FPI portfolio houses recognised | unit | all true | PASS |
| TC-2 | unit | 9 real foreign strategic/PE entities excluded | unit | all false | PASS |
| TC-3 | unit | 7 real domestic prop/HFT desks excluded | unit | all false | PASS |
| TC-4 | unit | Indian arms of global brands are DII | edge | HSBC/Invesco/Franklin MF false | PASS |
| TC-5 | unit | the offshore arm of the same brand still counts | edge | true | PASS |
| TC-6 | unit | Indian insurers and AIFs with fund-like names stay DII | edge | HDFC Life, 360 ONE false | PASS |
| TC-7 | unit | one-sided selling → `hs`, buying → `hb` | unit | codes | PASS |
| TC-8 | unit | rotation (500 in / 480 out) is not distribution | edge | `n` | PASS |
| TC-9 | unit | a tiny print never reads as heavy | edge | `n` | PASS |
| TC-10 | unit | codes are the tracker's own option values | unit | subset | PASS |
| TC-11 | api | symbols with real FPI deals score a direction | api | `hb` + evidence | PASS |
| TC-12 | api | no deals at all → complete observation, scores `n` | api | filled | PASS |
| TC-13 | api | deals but none recognised → UNFILLED with names | failure | not scored | PASS |
| TC-14 | regression | full suite | unit | no new failures | PASS |

## The design decision I got wrong first, and reversed

My first implementation scored `n` (neutral, weight 20 **counted**) when deals existed
but no counterparty matched the whitelist. The first live run disproved that
immediately:

```
AGARWALEYE  [80/100]  deal='n'
   OK S3: 8 counterparty-side(s), none an identifiable FPI portfolio investor
          — Allianz Global Investors Gmbh Acting On Behalf Of Allianz Eee Fonds, Claymor…
```

**Allianz Global Investors is a genuine FPI.** The whitelist simply lacked it. So
"none recognised" was not "no FPI activity" — it was "our list missed one", and
scoring a neutral there is precisely the fabricated neutral the rest of this design
refuses. It adds weight 20 of non-evidence that the composite then treats as evidence.

Corrected to three branches:

- **FPI recognised** → score the direction. High confidence.
- **Deals exist, none recognised** → stream stays **unfilled**, reason names who *was*
  there, so a reader can judge the miss.
- **No deals at all** → filled as `n`. This one *is* complete information: any
  qualifying trade must be disclosed, so absence is an observation.

The whitelist was then widened from the same evidence (Allianz GI, Polar Capital,
Jupiter India, Polunin EM, `MASTER FUND`, `FUNDS PLC`, ` VCC`), and Indian
institutions with fund-like names excluded (HDFC Life, SBI Life, ICICI Pru Life,
Tata AIA, Nuvama, 360 ONE).

## Live results after the correction (TC-11/12/13)

```
PAYTM       [90/100]  deal='hb'  FPI net +1,340.1 cr on 1,340.1 cr gross across 8 sides
                                 — Bnp Paribas Financial Markets - Odi, Ghisallo Master Fund Lp,
                                   Goldman Sachs Bank Europe…
IIFL        [80/100]  deal='hb'  FPI net +728.4 cr on 728.4 cr gross — Smallcap World Fund Inc
KALYANKJIL  [90/100]  deal='hb'  FPI net +385.5 cr on 394.7 cr gross — Bofa Securities Europe Sa
BIOCON      [90/100]  deal='hb'  FPI net +135.1 cr on 135.1 cr gross across 5 sides
AGARWALEYE  [80/100]  deal='hb'  FPI net +270.5 cr on 270.5 cr gross
                                 — Allianz Global Investors Gmbh…, Polar Capital Funds Plc
SUNTECK     [80/100]  deal='n'   FPI net -10.1 cr on 74.8 cr gross  (two-sided → not distribution)
RELIANCE    [90/100]  deal='n'   No bulk or block deal disclosed for this symbol in the window
```

AGARWALEYE going `n` → `hb` between runs is the whitelist widening working, and it was
visible only because the evidence line names counterparties.

SUNTECK is the scoring rule earning its place: −10.1 cr net on 74.8 cr gross is a fund
rotating, not exiting, so it scores `n` rather than "selling".

## Scoring basis

Direction is scored on how **one-sided** the activity was — net as a share of gross —
not on the rupee figure. A fund moving 500 cr in and 480 cr out is churn; a fund
selling 60 cr with nothing on the other side is distribution. Bands at ±25 % and ±75 %
of gross, with a 5 cr absolute floor so a single small print never reads as "heavy".

`repeatSeller` is set when a recognised FPI sold on more than one day — the tracker's
own flag for a staggered exit, which is the classic distribution footprint.

## Coverage, honestly

Over a 45-day window: **365 symbols had any bulk/block deal; 18 involved a recognisable
FPI house.** Most large caps have none at all — a bulk deal needs >0.5 % of listed
shares, which for RELIANCE is enormous. So for most symbols S3 resolves via the
"no deals disclosed" branch, which is a real reading rather than a gap.

## Regression (TC-14)

```
$ python3 -m pytest nidp/tests/services/test_flow_ledger.py -q
91 passed in 0.12s

$ python3 -m pytest nidp/tests nidp/services/quality_gate/tests -q --ignore=<4 fastapi-less modules>
3 failed, 662 passed, 6 skipped in 5.20s
```

The 3 failures are pre-existing and unrelated (`test_mf_amc_robustness` ×2,
`test_feed_registry_drift`), proven earlier this session by re-running with my changes
stashed.

## UNVERIFIED

- **The whitelist is curated and will keep missing names.** That is a permanent
  property, not a bug to close — which is why an unrecognised counterparty leaves the
  stream unfilled rather than scoring a neutral, and why the evidence always names who
  was seen.
- **Not deployed.** These run through the real handler against the real DB; the DaaS
  container still carries the previous router.

## Verdict: PASS
