# Trendlyne PIT Audit — Success & Acceptance Criteria Matrix

Owner's matrix, 2026-09-19. Each ID is reported in `PIT_AUDIT.md` as PASS / FAIL / UNVERIFIED with its evidence.
Owner's approval status: *approved for audit implementation after incorporating the timestamp, decision-cutoff,
revision classification and leakage-testing gates.*

## 1. Governance, scope & PIT definitions
| ID | Workstream | Success criteria | Acceptance criteria | Evidence / validation |
|---|---|---|---|---|
| G-01 | PRD preservation | Existing PRDs remain unchanged and traceable | Both PRDs copied verbatim; README states v1.1 supersedes v1.0 | File comparison with original checksums |
| G-02 | Scope isolation | Audit does not affect production systems | No changes to model, paper trading, NIDP services, tables, or crons | Git diff and code review |
| G-03 | Audit scope | Results are clearly limited to tested coverage | Sample, period, metrics, formats, and limitations documented | Scope section in audit report |
| G-04 | PIT definitions | PIT concepts are unambiguous | period_end, submitted_at, broadcast_at, available_at, and retrieved_at defined separately | Data contract review |
| G-05 | Decision cutoff | Historical features cannot use future information | Every eligibility decision uses explicit decision_at or feature_cutoff_at | Automated leakage tests |

## 2. Trendlyne capability audit
| ID | Workstream | Success criteria | Acceptance criteria | Evidence / validation |
|---|---|---|---|---|
| TL-01 | As-of capability | Actual Trendlyne API capabilities are established | Test date/as-of parameters and record accepted/rejected behavior | Raw request and response archive |
| TL-02 | Schema validation | Tool schemas and parameter limitations are documented | Check date parameters, additionalProperties, response fields, and descriptions | Schema snapshot and hash |
| TL-03 | Lag-code interpretation | Lag codes are not assumed to be PIT-valid | Test codes across reporting periods, stocks, and archive dates | Lag-code validation matrix |
| TL-04 | Data definitions | Metric definitions and units are understood | Record units, methodology, basis, and magnitude checks against NSE | Reconciliation report |
| TL-05 | Server metadata | Trendlyne responses are reproducible | Store server/version metadata and response-schema hash where available | Archive metadata |
| TL-06 | Category verdict | Each category receives an evidence-based classification | Financials, ownership, events, ratios, and news receive individual verdicts | Category verdict table |

## 3. NSE/BSE ground truth & parser validation
| ID | Workstream | Success criteria | Acceptance criteria | Evidence / validation |
|---|---|---|---|---|
| NSE-01 | Parser fixtures | Existing parsers reproduce verified source values | Fixtures cover old Reg-33, Integrated Filing, consolidated, standalone, and old/new shareholding formats | Fixture test results |
| NSE-02 | Raw-field preservation | Original exchange metadata remains available | Preserve broadcastDate, submissionDate, sequence and filing IDs without overwriting | Raw-versus-parsed comparison |
| NSE-03 | Filing coverage | Data availability is understood by metric and period | Coverage table identifies available metrics, timestamps, formats, and revisions | Coverage matrix |
| NSE-04 | Timestamp integrity | Filing timestamps are not incorrectly inferred | Missing or contradictory public timestamps are marked UNVERIFIED | Timestamp validation report |
| NSE-05 | Revision handling | First-filed and revised filings are preserved | No revision overwrites an earlier filing; chronology is retained | Revision test fixtures |
| NSE-06 | Source traceability | Every parsed value can be traced to source evidence | Store source URL, retrieval time, parser version, and SHA-256 artifact hash | Filing record inspection |

## 4. Immutable NSE filing archive
| ID | Workstream | Success criteria | Acceptance criteria | Evidence / validation |
|---|---|---|---|---|
| ARC-01 | Append-only storage | Historical source records remain immutable | Use append-only jsonl.gz and raw artifacts; never overwrite revisions | File and hash checks |
| ARC-02 | Filing identity | Filings are uniquely identifiable | Record symbol, ISIN, exchange, filing ID, period, and revision information | Schema validation |
| ARC-03 | Metric provenance | Each metric has complete source context | Store metric name, value, unit, statement type, and consolidation type | Record-level validation |
| ARC-04 | Revision summary | Value history is retained | Store as_filed_value, latest_known_value, first_filed_at, and latest_revision_at | Revision reconciliation |
| ARC-05 | Reproducibility | Archive can be reconstructed and audited | Raw artifacts have stable hashes and parser versions | Re-run validation |

## 5. Availability & session mapping
| ID | Workstream | Success criteria | Acceptance criteria | Evidence / validation |
|---|---|---|---|---|
| AV-01 | Availability semantics | Public availability is distinguished from submission | Record submitted_at, broadcast_at, and verified document availability separately | Timestamp evidence |
| AV-02 | Availability confidence | Uncertain timestamps are not treated as exact | Store availability evidence and confidence level | Policy test |
| AV-03 | Session mapping | Features are mapped to the correct decision session | Test pre-open, intraday, after-close, and non-trading-day scenarios | Unit tests |
| AV-04 | Decision cutoff | No feature is used before it becomes available | Require available_at <= decision_at | Leakage test |
| AV-05 | Timezone/calendar | Market timing is consistently interpreted | Use IST and validated exchange trading calendar | Calendar test |
| AV-06 | Event availability | Event date is not assumed to equal public availability | Compare event date with exchange broadcast/publication date | Event timing report |

## 6. Trendlyne–NSE comparison
| ID | Workstream | Success criteria | Acceptance criteria | Evidence / validation |
|---|---|---|---|---|
| CMP-01 | First-filed comparison | Trendlyne values are compared with first-filed values | Compare Trendlyne against first-filed NSE records | Comparison output |
| CMP-02 | Latest revision comparison | Current representation is separately evaluated | Compare Trendlyne against latest revised NSE values | Reconciliation output |
| CMP-03 | Period mapping | Equivalent reporting periods are compared | Validate fiscal period, quarter, year, and filing type | Period mapping tests |
| CMP-04 | Basis matching | Consolidated and standalone values are not mixed | Compare matching statement bases only | Basis validation |
| CMP-05 | Units and definitions | Differences are not falsely classified as errors | Validate units, definitions, rounding, and normalization | Difference reason codes |
| CMP-06 | Missingness | Missing data is visible and measurable | Report missing, missing-to-present, and zero-to-nonzero changes | Missingness report |
| CMP-07 | Ownership mapping | Ownership categories are comparable | Document FII/FPI and DII/MF mapping and corporate-action effects | Ownership mapping report |
| CMP-08 | Timing comparison | Data matching is separated from availability | Compare broadcast, submission, Trendlyne retrieval, and archive timestamps | Timing analysis |

## 7. Tolerances, restatements & materiality
| ID | Workstream | Success criteria | Acceptance criteria | Evidence / validation |
|---|---|---|---|---|
| TOL-01 | Metric tolerances | Differences are assessed using metric-specific rules | Configure absolute and relative tolerance per metric | Tolerance configuration |
| TOL-02 | Edge cases | Small, zero, negative, and missing values are handled | Tests cover zero denominators, negative PAT, missing values, and sign changes | Unit tests |
| TOL-03 | Materiality | Numerical matching is separated from economic significance | Report tolerance result and materiality result independently | Comparison report |
| TOL-04 | Restatement classification | Restatements are not inferred from differences alone | Distinguish revisions, normalization, period mapping, and unresolved differences | Reason-code report |
| TOL-05 | Revision chronology | Historical values remain time-accurate | Follow first-filed and revision sequence before classification | Filing chronology |
| TOL-06 | Unresolved differences | Unexplained discrepancies are not silently accepted | Classify as DIFFERS_UNEXPLAINED or UNVERIFIED | Exception report |

## 8. Ownership, events & news
| ID | Workstream | Success criteria | Acceptance criteria | Evidence / validation |
|---|---|---|---|---|
| CAT-01 | Ownership | Ownership data is tied to disclosure availability | Quarter-end date and disclosure date stored separately | Ownership audit |
| CAT-02 | Ownership classification | Historical ownership is not used without timing evidence | Missing disclosure timestamp leads to UNVERIFIED unless approved rule exists | Eligibility test |
| CAT-03 | Corporate actions | Ownership changes are interpreted correctly | Consider QIPs, splits, bonuses, mergers, and other relevant actions | Corporate-action examples |
| CAT-04 | Events | Event categories have individual PIT rules | Validate board meetings, SAST, deals, results, and corporate actions separately | Event verdict table |
| CAT-05 | News | Latest-only news is not treated as historical | News is FORWARD_ONLY unless completeness and historical availability are proven | News capability evidence |
| CAT-06 | Event availability | Event dates are not sufficient evidence | Public availability is established independently where required | Timestamp comparison |

## 9. Model data policy & feature store
| ID | Workstream | Success criteria | Acceptance criteria | Evidence / validation |
|---|---|---|---|---|
| POL-01 | Category policy | Every category has an approved usage rule | Assign one PIT class per tested category and scope | PIT_AUDIT.md |
| POL-02 | Feature metadata | Feature provenance is complete | Include period_end, available_at, retrieved_at, source, pit_class, and data_version | Schema test |
| POL-03 | PIT flag | point_in_time_validated is derived consistently | Define mapping from PIT class to the PRD flag | Policy unit test |
| POL-04 | Historical eligibility | Invalid data is blocked from historical modeling | Permit only approved PIT classes with valid availability and cutoff timestamps | Eligibility tests |
| POL-05 | Forward-only data | Current data cannot enter historical training | Mark Trendlyne current data and unvalidated data as FORWARD_ONLY or UNVERIFIED | Negative test |
| POL-06 | Rule governance | Rule-based validation is controlled | Store rule ID, version, validation sample, coverage, and approval status | Rule metadata review |

## 10. Sample, execution & operational safety
| ID | Workstream | Success criteria | Acceptance criteria | Evidence / validation |
|---|---|---|---|---|
| OPS-01 | Sample design | Sample is reproducible and diverse | 40 stocks: 30 fixed-seed random and 10 risk-focused stocks | Sample manifest |
| OPS-02 | Time window | Audit covers the defined period | Sep 2024–Jun 2026 and eight quarters | Scope validation |
| OPS-03 | NSE collection | Collection is controlled and traceable | Paced requests, retry handling, proxy fallback, and failure logging | Execution log |
| OPS-04 | Trendlyne budget | API usage remains controlled | Trendlyne calls remain within 60 | Redis counter and report |
| OPS-05 | Request estimate | Request volume is evidence-based | Estimate based on stocks, quarters, endpoints, retries, and revisions | Budget calculation |
| OPS-06 | Data isolation | Production environment remains unaffected | No NIDP database connection or production writes | Grep and code review |
| OPS-07 | Credential safety | Secrets are protected | No credentials in source, logs, or audit artifacts | Secret scan |

## 11. Testing & manual verification
| ID | Workstream | Success criteria | Acceptance criteria | Evidence / validation |
|---|---|---|---|---|
| QA-01 | Fixture tests | Parsers reproduce hand-read values | All approved fixtures pass | Test output |
| QA-02 | Timestamp tests | Availability and cutoff rules work correctly | Test timestamp ordering, session mapping, and timezone handling | Unit test results |
| QA-03 | Revision tests | First-filed values are not overwritten | Test revision chronology and latest-value separation | Unit test results |
| QA-04 | Classification tests | PIT classes are assigned consistently | Test all six classes and invalid/missing evidence | Unit test results |
| QA-05 | Leakage tests | Future information is rejected | Test post-decision filings, revised values, and current Trendlyne values | Negative test results |
| QA-06 | Manual checks | Automated results match source documents | Validate three stocks against filing PDFs, including PAT, broadcast time, and promoter percentage | Manual review record |
| QA-07 | Regression safety | Existing functionality remains unaffected | Existing relevant tests pass; production files show no unintended changes | CI/test report |

## 12. Final deliverables & approval
| ID | Workstream | Success criteria | Acceptance criteria | Evidence / validation |
|---|---|---|---|---|
| DEL-01 | Audit report | Findings are decision-ready | Include methodology, sample, coverage, comparisons, limitations, and verdicts | PIT_AUDIT.md |
| DEL-02 | Verdict table | Each category has a justified PIT classification | Report Q1, Q2, and Q3 outcomes with evidence and coverage limits | Category matrix |
| DEL-03 | Policy mapping | PRD requirements are operationalized | Document how point_in_time_validated is derived | Policy section |
| DEL-04 | Coverage statement | Sample-based conclusions are not generalized | Explicitly list tested and untested categories, formats, and periods | Coverage report |
| DEL-05 | Audit commit | Only approved audit changes are committed | Review Git diff and commit audit files only | Commit review |
| DEL-06 | Approval gate | Historical model integration is controlled | Owner approval required before using newly certified data in model training or backtesting | Approval record |

## Final definition of done
| Gate | Required outcome | Pass condition |
|---|---|---|
| PIT semantics | Clear availability and decision-time definitions | All timestamps and cutoff rules documented |
| Data integrity | First-filed and revised values preserved | No silent overwrites |
| Trendlyne validation | Category-level evidence collected | No unsupported global certification |
| NSE validation | Filing-level ground truth established | Parser and timestamp tests pass |
| Comparison quality | Differences are explained or flagged | No unexplained difference is silently accepted |
| Leakage prevention | Future information is blocked | All negative PIT tests pass |
| Model integration | Policy is enforceable | Feature-level eligibility gate implemented and tested |
| Governance | Audit is independently reviewed | Owner approval before historical model use |
