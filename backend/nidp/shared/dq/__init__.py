"""NIDP Data Quality Gates — shared framework.

Public API:

    from nidp.shared.dq import (
        Severity, Verdict, GateResult, GateCheckFailed,
        BaseGate, emit_verdict,
        SnapshotCompletionGate,
    )

Every gate is a subclass of BaseGate.  Call:

    result = await gate.run(conn, target_date, job_run_id=...)
    # GateCheckFailed is raised if any P0 check fails (caller decides to abort).
"""
from nidp.shared.dq.gate import (          # noqa: F401
    BaseGate,
    GateCheckFailed,
    GateResult,
    Severity,
    Verdict,
    emit_verdict,
)
from nidp.shared.dq.gate3_snapshot import SnapshotCompletionGate  # noqa: F401
