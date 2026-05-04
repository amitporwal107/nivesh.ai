"""pytest config — make `nidp` importable when running from repo root."""
from __future__ import annotations

import sys
from pathlib import Path

# Add backend/ to sys.path so `import nidp.xxx` works without a
# package-install step. This is the pattern existing backend tests
# also rely on.
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
