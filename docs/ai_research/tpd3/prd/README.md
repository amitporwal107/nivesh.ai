# Nivesh.ai PRDs

| File | Version | Date | Status |
|---|---|---|---|
| `Nivesh_AI_Complete_PRD_v1.1_Paper_Trading_Updated.md` | **1.1 (current)** | 2026-09-19 | Proposed — research-first, manual paper trading only |
| `Nivesh_AI_Complete_PRD_v1.0.md` | 1.0 (superseded by 1.1) | 2026-09-19 | Proposed — research-first, manual execution only |
| `Nivesh_Risk_Allocation_Engine_PRD_v1.0.md` | Module PRD 1.0 | 2026-09-19 | Proposed — Risk Management & Capital Allocation Engine (paper-only, cash equity, long only, positional); details PRD v1.1 §32.4–32.7 and §32.14 |

**v1.1 supersedes v1.0.** Sections 1–27 are identical apart from the version and status lines; v1.1 adds §32 Paper
Trading Specification (modes A–D, eligibility, account configuration, sizing, entry/exit simulation, alerts, ledger,
metrics, windows, stop conditions, acceptance criteria, revised Track 1/2), §33 Revised Product Decisions,
§34 Implementation Priority Update (P0–P3) and §35 Final Paper Trading Principle.

Saved from the owner's attachments on 2026-09-19 (the original files were not on disk, so the text was written from
the attachment content). SHA-256 of the saved files, for comparison with the originals (acceptance criterion G-01):

| File | SHA-256 |
|---|---|
| Nivesh_AI_Complete_PRD_v1.0.md | `57a66f77963bfe686a0ace4386c81e54ffcc88444158ec1f4baf7ceeefa9285a` |
| Nivesh_AI_Complete_PRD_v1.1_Paper_Trading_Updated.md | `ccc70e6f469c326226ccbf83c5cb6981d965bf8f9a63b28029c585a91f3bfd6e` |
| Nivesh_Risk_Allocation_Engine_PRD_v1.0.md | `e451a42ceb208b13943827de56cbb61c72dfdd3420be557fec987fd9f9489ea6` |

The risk-engine PRD came as a PDF ("Position Sizing Summary.pdf", 35 pages), which is not on disk either. Its text is
transcribed verbatim; its six diagrams (system flow, allocation process, drawdown state machine, execution flow,
experiment workflow, entity relationship) are reproduced as mermaid; its §25 decision checklist was empty in the
attachment and is marked as such.

Related: the Trendlyne point-in-time audit (`../data/PIT_AUDIT.md`) implements the PRD's §5/§10 Trendlyne checks and
P2 "Trendlyne point-in-time certification"; its acceptance matrix is `../data/PIT_AUDIT_ACCEPTANCE.md`.
