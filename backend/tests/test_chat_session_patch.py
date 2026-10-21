from routes.chat import SessionPatch, _clean_tags


def test_clean_tags_normalises_dedupes_and_caps():
    raw = ["  IT  Sector ", "it sector", "", "x" * 40] + [f"t{i}" for i in range(20)]
    out = _clean_tags(raw)
    assert out[0] == "it sector"
    assert out[1] == "x" * 24
    assert len(out) == 8
    assert len(set(out)) == len(out)


def test_patch_model_fields_optional():
    assert SessionPatch().bookmarked is None and SessionPatch().tags is None
