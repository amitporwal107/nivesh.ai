"""Versioned scoring policies for the replay engine.

A policy bundles the five weights (A/C/L/F/K) plus certification and
publish-gate thresholds. Stored in `audit.policy_versions`; loaded into
a `ScoringPolicy` dataclass for thread-safe in-process use.

Default policies (seeded by migration 044):
  - `legacy` — pre-replay weights: Q = 0.40A + 0.30C + 0.15P + 0.10F + 0.05U
  - `v1`     — PRD-spec weights:   Q = 0.30A + 0.25C + 0.20L + 0.15F + 0.10K
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

import asyncpg


@dataclass(frozen=True)
class ScoringPolicy:
    version: str
    description: str
    # Five-dimension weights (must sum to ~1.0). Names match the spec:
    #   A = accuracy, C = consistency, L = completeness,
    #   F = freshness, K = confidence (or auditability in legacy)
    w_accuracy:     float
    w_consistency:  float
    w_completeness: float
    w_freshness:    float
    w_confidence:   float
    # Certification thresholds (overall_score Q lower-bounds).
    cert_gold:    float = 99.0
    cert_silver:  float = 95.0
    cert_review:  float = 90.0
    # Publish gate cutoffs.
    publish_min:    float = 95.0
    review_min:     float = 90.0
    confidence_min: float = 90.0

    def weights_sum(self) -> float:
        return round(
            self.w_accuracy + self.w_consistency + self.w_completeness
            + self.w_freshness + self.w_confidence, 4
        )

    def score(
        self,
        accuracy: float,
        consistency: float,
        completeness: float,
        freshness: float,
        confidence: float,
    ) -> float:
        """Compute weighted overall score Q under this policy."""
        return round(
            self.w_accuracy     * accuracy
            + self.w_consistency  * consistency
            + self.w_completeness * completeness
            + self.w_freshness    * freshness
            + self.w_confidence   * confidence,
            3,
        )

    def certify(self, q: float) -> str:
        """Return certification tier for an overall score."""
        if q >= self.cert_gold:
            return "GOLD"
        if q >= self.cert_silver:
            return "SILVER"
        if q >= self.cert_review:
            return "REVIEW"
        return "REJECTED"

    def publish_decision(self, q: float, k: Optional[float] = None) -> str:
        """Return the publish-gate decision (PUBLISH | REVIEW | REJECT)."""
        if q < self.review_min:
            return "REJECT"
        if k is not None and k < self.confidence_min:
            return "REVIEW"
        if q < self.publish_min:
            return "REVIEW"
        return "PUBLISH"

    def as_dict(self) -> Dict[str, float]:
        return asdict(self)


# In-process built-in fallbacks (in case migration 044 hasn't been
# applied or `audit.policy_versions` is unreachable).
_BUILTIN: Dict[str, ScoringPolicy] = {
    "legacy": ScoringPolicy(
        version="legacy",
        description="Pre-replay weights: Q = 0.40A + 0.30C + 0.15P + 0.10F + 0.05U",
        w_accuracy=0.40, w_consistency=0.30, w_completeness=0.15,
        w_freshness=0.10, w_confidence=0.05,
        cert_gold=99.5, cert_silver=95.0, cert_review=90.0,
        publish_min=95.0, review_min=90.0, confidence_min=90.0,
    ),
    "v1": ScoringPolicy(
        version="v1",
        description="PRD-spec weights: Q = 0.30A + 0.25C + 0.20L + 0.15F + 0.10K",
        w_accuracy=0.30, w_consistency=0.25, w_completeness=0.20,
        w_freshness=0.15, w_confidence=0.10,
        cert_gold=99.0, cert_silver=95.0, cert_review=90.0,
        publish_min=95.0, review_min=90.0, confidence_min=90.0,
    ),
}


async def get_policy(
    conn: Optional[asyncpg.Connection],
    version: str,
) -> ScoringPolicy:
    """Load a named policy from audit.policy_versions; falls back to
    built-in defaults if the table is missing or the row isn't seeded."""
    if conn is not None:
        try:
            row = await conn.fetchrow(
                "SELECT * FROM audit.policy_versions WHERE version=$1",
                version,
            )
            if row:
                return ScoringPolicy(
                    version=row["version"],
                    description=row["description"] or "",
                    w_accuracy=float(row["w_accuracy"]),
                    w_consistency=float(row["w_consistency"]),
                    w_completeness=float(row["w_completeness"]),
                    w_freshness=float(row["w_freshness"]),
                    w_confidence=float(row["w_confidence"]),
                    cert_gold=float(row["cert_gold"]),
                    cert_silver=float(row["cert_silver"]),
                    cert_review=float(row["cert_review"]),
                    publish_min=float(row["publish_min"]),
                    review_min=float(row["review_min"]),
                    confidence_min=float(row["confidence_min"]),
                )
        except asyncpg.UndefinedTableError:
            pass
        except Exception:                                                 # noqa: BLE001
            # Schema not yet migrated → fall through to built-in.
            pass
    if version in _BUILTIN:
        return _BUILTIN[version]
    raise ValueError(
        f"unknown policy version '{version}'. "
        f"Built-in: {sorted(_BUILTIN)}; ensure migration 044 has been applied."
    )


async def list_policies(conn: Optional[asyncpg.Connection]) -> List[ScoringPolicy]:
    """Return every policy registered in audit.policy_versions; falls
    back to BUILTINs."""
    if conn is not None:
        try:
            rows = await conn.fetch(
                "SELECT version FROM audit.policy_versions ORDER BY version"
            )
            return [await get_policy(conn, r["version"]) for r in rows]
        except asyncpg.UndefinedTableError:
            pass
        except Exception:                                                 # noqa: BLE001
            pass
    return list(_BUILTIN.values())
