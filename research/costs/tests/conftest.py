"""Make `research.costs` importable when pytest runs from anywhere (same convention as
research/charting/tests/conftest.py and research/index_history/tests/conftest.py)."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
