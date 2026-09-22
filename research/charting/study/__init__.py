"""Study package -- CHARTING_PREREGISTRATION_V1 (docs/ai_research/CHARTING_PREREGISTRATION_V1.md)
§7 (report contents) and §8 (integrity rules), plus the study driver that assembles the two
development segments (§3) into a hashed run artifact.

Public surface:
  - `report` -- pure aggregation over already-built event/control rows (`research.charting.
    events`'s own row schema) into the §7 report tables. Never touches real data itself.
  - `run` -- the study driver: universe rule, segment split, demerger-exclusion hook, hashed
    run-folder write (task item 4). Built, NOT run on the real universe in this session (see
    its own module docstring).
  - `integrity` -- the §8 integrity checks as callable functions + their own tests: kill
    switch, sealed-window absence, independent recomputation sampler.
"""
from research.charting.study import integrity, report, run

__all__ = ["integrity", "report", "run"]
