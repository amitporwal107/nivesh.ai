"""Unit tests for the shared OpenAI embedding client (nidp.shared.embeddings).

No network / no openai package required: we inject a fake client into the
module global so the batching + ordering + pgvector-literal logic is exercised
deterministically.
"""
import nidp.shared.embeddings as emb


class _FakeEmbeddings:
    def __init__(self, dim=1536):
        self.dim = dim
        self.calls = []

    def create(self, model, input):
        self.calls.append({"model": model, "n": len(input)})
        # Echo a deterministic vector per input; return OUT OF ORDER on purpose
        # so the sort-by-index realignment is actually tested.
        class _Item:
            def __init__(self, index, vec):
                self.index = index
                self.embedding = vec

        items = [_Item(i, [float(i)] * self.dim) for i in range(len(input))]
        return type("Resp", (), {"data": list(reversed(items))})()


class _FakeClient:
    def __init__(self):
        self.embeddings = _FakeEmbeddings()


def _install_fake(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(emb, "_client", fake)
    return fake


# ── to_pgvector_literal (pure) ───────────────────────────────────────

def test_pgvector_literal_format():
    assert emb.to_pgvector_literal([0.1, 0.2, 0.3]) == "[0.1,0.2,0.3]"
    assert emb.to_pgvector_literal([]) == "[]"


def test_pgvector_literal_roundtrips_dim():
    vec = [0.0] * emb.EMBED_DIM
    lit = emb.to_pgvector_literal(vec)
    assert lit.startswith("[") and lit.endswith("]")
    assert lit.count(",") == emb.EMBED_DIM - 1


# ── batching + order preservation ────────────────────────────────────

def test_embed_sync_preserves_order_across_reversed_response(monkeypatch):
    _install_fake(monkeypatch)
    out = emb._embed_sync(["a", "b", "c"])
    # Despite the fake returning reversed data, output realigns to input order.
    assert [v[0] for v in out] == [0.0, 1.0, 2.0]
    assert all(len(v) == emb.EMBED_DIM for v in out)


def test_embed_sync_batches_over_max_batch(monkeypatch):
    fake = _install_fake(monkeypatch)
    n = emb._MAX_BATCH * 2 + 5
    out = emb._embed_sync([f"t{i}" for i in range(n)])
    assert len(out) == n
    # 3 API calls: two full batches + a remainder.
    assert len(fake.embeddings.calls) == 3
    assert fake.embeddings.calls[0]["n"] == emb._MAX_BATCH


def test_embed_sync_empty_returns_empty(monkeypatch):
    _install_fake(monkeypatch)
    assert emb._embed_sync([]) == []


def test_blank_text_still_gets_a_vector(monkeypatch):
    _install_fake(monkeypatch)
    out = emb._embed_sync(["", "   ", "real"])
    assert len(out) == 3  # blanks are sent as a space, not dropped


def test_is_configured(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert emb.is_configured() is False
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert emb.is_configured() is True
