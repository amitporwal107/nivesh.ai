"""A5 (branch a — user-accepted 2026-09-14): `fno` membership dropped, no today's-list lookups in history.

nidp.fno_bhavcopy starts 2026-04-10 and research used today's fo_mktlots.csv / sec_list.csv for every
historical date (bm_data.py:409, :454-456, :542-547).
"""
import re
from pathlib import Path


TODAY_LISTS = re.compile(r"fo_mktlots|sec_list\.csv|band_now|fo_mktlots\.csv")


def test_feature_list_has_no_fno_or_band_membership():
    from nidp.services.tpd_model.features import FEATURE_LIST

    bad = [f for f in FEATURE_LIST if re.search(r"(^|_)(fno|f_?o_?member|mktlot|lot_size|band)(_|$)", f)]
    assert bad == []


def test_model_package_never_reads_todays_reference_lists():
    import nidp.services.tpd_model as pkg

    hits = [str(p) for p in Path(pkg.__file__).parent.rglob("*.py") if TODAY_LISTS.search(p.read_text())]
    assert hits == []
