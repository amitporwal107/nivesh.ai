# Pillar 5 — SEBI & Regulatory Compliance

**Honesty posture for this pillar (read first):** regulatory *frameworks* are stable and
stated below; specific *numbers* (net-worth, fee caps, registration fees, tax rates, thresholds)
change with circulars and Finance Acts. **Never assert a numeric threshold from memory — mark it
`verify against the current SEBI master circular / Finance Act` and, where it matters, fetch the
live regulation (WebSearch/WebFetch to sebi.gov.in / amfiindia.com).** This expert advises the
*builders* on how to keep the product compliant; it is **not** a registered adviser and its
output is not legal advice. When a design decision turns on a live legal threshold, that's
`NEEDS-INPUT` for compliance/legal sign-off, not a guess.

## The real guard already in the code — align to it, don't reinvent
`backend/nidp/services/copilot_agent/nodes/compliance.py` is the **final node** of the copilot
graph and already enforces: a mandatory SEBI disclaimer, a numeric-grounding hallucination guard,
and a length cap. Any user-facing wording you design must be consistent with this node — extend
it, cite it, and make sure your recommendation passes through it, rather than adding a parallel
disclaimer scheme. `_llm.py` carries anti-hallucination rules; `llm_safety.py` guards output.

## Which regulatory hat is the product wearing? (this decides what it may SAY)
The permitted output changes entirely by registration — establish it before framing advice
(`routes/copilot.py` advisor-vs-investor gating is where this bites):
- **MF Distributor (ARN, AMFI-registered):** may *execute* and describe products; advice is only
  "incidental" to distribution; earns commission; **must not** hold out as an independent adviser
  or charge a separate advisory fee on the same assets. Follows the **AMFI Code of Conduct**.
- **Registered Investment Adviser (RIA — SEBI IA Regulations, 2013 + amendments):** fee-only,
  **fiduciary**, must do **risk profiling + suitability** before any recommendation, segregate
  advisory from distribution at client level, disclose conflicts, maintain records. Fee model and
  net-worth/qualification thresholds are regulated — *verify current values*.
- **Research Analyst (RA — SEBI RA Regulations, 2014):** may publish research/"buy-sell-hold"
  with mandated **disclosures** (holdings, conflicts, past recommendation performance) and a
  disclaimer; distinct from personalised advice.
Get this wrong and a compliant number becomes a regulatory breach. If the hat is unclear for a
given surface, `NEEDS-INPUT`.

## Obligations that shape every user-facing analytic
1. **Suitability & risk profiling.** No recommendation without a risk profile and a
   goal/horizon fit. Anchors: `backend/services/risk_profile_chat.py`,
   `copilot_agent/nodes/risk.py`, `copilot_tools/risk.py`. Capacity vs tolerance vs need must
   reconcile (see `mutual-fund-advisory.md`).
2. **No assured/guaranteed returns.** Never imply certainty. Projections must be labelled
   assumptions with ranges/sensitivity (the goal engine's Monte-Carlo is the honest way to show
   uncertainty), never a single promised figure.
3. **Fair, non-misleading performance.** Standardised return methodology, the correct benchmark,
   the window stated, **"past performance is not indicative of future results,"** and — for MFs —
   the statutory **"Mutual fund investments are subject to market risks, read all scheme related
   documents carefully."** Point-to-point cherry-picking is misleading; prefer rolling returns.
4. **Conflict-of-interest & fee disclosure.** Commission (regular vs direct), any distribution
   relationship, and material conflicts disclosed. Direct-vs-regular must be presented honestly
   because it directly affects the investor's return.
5. **Advertising / communication code.** Disclaimers, risk factors, no selective highlighting,
   substantiated claims. Balance every reward statement with its risk.
6. **Record-keeping & auditability.** Advice, its rationale, and the data it rested on must be
   reproducible — which is exactly why this whole expert is built on **live retrieval with the
   source shown**.

## Data protection is compliance too — DPDP Act, 2023
Handled in `backend/routes/compliance.py` (consents, audit trail, PAN encrypt/erase, data export,
right-to-erasure) + `services/{consents,audit,pii_security,malware_scanner,identity_uniqueness}.py`.
Principles to honour in any feature: **consent + purpose limitation, data minimisation, security
(PAN/Aadhaar encrypted, PII never in logs/prompts/output), retention limits, and the user's rights
(access, correction, erasure).** Mask PII in every analysis you return.

## KYC & investor onboarding
KYC (PAN, and KYC-registration status) is a precondition to transacting; the product treats PAN as
regulated PII (ciphertext via `pii_security.py`). Don't design a flow that recommends a
transactable action to a non-KYC'd / non-suitable user.

## The compliance review checklist (run it on any advice-bearing output)
- [ ] Correct regulatory hat established (Distributor / RIA / RA) for this surface.
- [ ] Risk profile + suitability present; horizon/goal fit shown.
- [ ] No assured-return / guaranteed language; projections are ranges with assumptions.
- [ ] Performance is standardised, benchmarked, windowed, with the past-performance + market-risk
      disclaimers; not cherry-picked.
- [ ] Conflicts/commissions and direct-vs-regular disclosed.
- [ ] Passes through the real `compliance.py` guard (disclaimer + numeric grounding).
- [ ] PII masked; DPDP consent/purpose respected.
- [ ] Every regulatory *number* marked "verify against current SEBI circular / Finance Act,"
      not asserted from memory.

## Definition of Done for a compliance review
The regulatory hat is named; the checklist above is applied to the specific output; the framing
aligns with the real `compliance.py` node; numeric thresholds are flagged for live verification
(and fetched when the decision depends on them); PII/DPDP handling is stated; anything requiring a
lawyer/compliance officer is surfaced as `NEEDS-INPUT`, not answered as fact.
