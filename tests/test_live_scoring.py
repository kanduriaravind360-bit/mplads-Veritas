"""Live Scoring must not depend on the sentence transformer loading.

The demo crashed with "Cannot copy out of meta tensor" when the transformer was
constructed inside the Streamlit process. These tests pin the three properties
that make that impossible to repeat: the demo corpus is served from cache, a
model failure degrades to TF-IDF instead of raising, and scoring works with no
GPU at all.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ml.config import load_config

ROOT = Path(__file__).resolve().parents[1]
DEMO_CSV = ROOT / "demo_data" / "live_demo_works.csv"


@pytest.fixture(scope="module")
def cfg() -> dict:
    return load_config("ml")


@pytest.fixture(scope="module")
def demo_frame() -> pd.DataFrame:
    if not DEMO_CSV.exists():
        pytest.skip("demo CSV not built in this environment")
    return pd.read_csv(DEMO_CSV).drop(columns=["demo_key", "expected_outcome"], errors="ignore")


def test_demo_corpus_is_served_from_cache(demo_frame: pd.DataFrame, cfg: dict) -> None:
    """The demo button must never need to load a model.

    If this fails, run `python -m ml.train` to warm the cache.
    """
    from ml.data import clean
    from ml.work_type import has_cached_embeddings

    prepared = clean(demo_frame, load_config("data"))
    assert has_cached_embeddings(prepared["work_description"], cfg), (
        "demo embeddings are not cached; the Live Scoring button would load the model"
    )


def test_embedding_falls_back_when_the_model_will_not_load(monkeypatch, cfg: dict) -> None:
    """A model failure must degrade to TF-IDF, not raise.

    This reproduces the reported crash directly: the loader is made to fail the
    way a meta tensor does, and the pipeline must still return vectors.
    """
    import ml.work_type as work_type
    from ml.pipeline import _embed_or_fall_back

    def _explode(*_args: object, **_kwargs: object) -> object:
        raise NotImplementedError("Cannot copy out of meta tensor; no data!")

    monkeypatch.setattr(work_type, "_MODEL", None)
    monkeypatch.setattr(work_type, "load_model", _explode)

    # A corpus with no cache entry, so the model path is the only one left.
    descriptions = pd.Series([f"Construction of a test work number {i}" for i in range(12)])
    vectors, source = _embed_or_fall_back(descriptions, cfg)

    assert source == "tfidf-fallback"
    assert vectors.shape[0] == len(descriptions)
    assert vectors.shape[1] > 1


def test_loader_recovers_when_low_cpu_mem_usage_is_rejected(monkeypatch, cfg: dict) -> None:
    """Older versions reject model_kwargs; the loader must try the next strategy."""
    import ml.work_type as work_type

    attempts: list[str] = []

    class _Fake:
        def __init__(self, _name: str, device: str = "cpu", **kwargs: object) -> None:
            if "model_kwargs" in kwargs:
                attempts.append("model_kwargs")
                raise TypeError("unexpected keyword argument 'model_kwargs'")
            attempts.append(f"plain:{device}")
            self.device = device
            self.max_seq_length = 0

        def to(self, device: str) -> _Fake:
            self.device = device
            return self

    monkeypatch.setattr(work_type, "_MODEL", None)
    monkeypatch.setattr(work_type, "torch_device", lambda: "cpu")
    monkeypatch.setitem(
        __import__("sys").modules,
        "sentence_transformers",
        type("m", (), {"SentenceTransformer": _Fake}),
    )

    model = work_type.load_model(cfg)
    assert model is not None
    assert attempts[0] == "model_kwargs", "the first strategy should be low_cpu_mem_usage=False"
    assert len(attempts) > 1, "the loader gave up instead of trying the next strategy"
    monkeypatch.setattr(work_type, "_MODEL", None)


def test_scoring_the_demo_csv_without_a_gpu(monkeypatch, demo_frame: pd.DataFrame) -> None:
    """The whole demo batch must score on CPU, which is the venue's likely case."""
    import torch

    import ml.gpu as gpu
    from ml.pipeline import score_new_works

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    gpu.torch_device.cache_clear()
    gpu.device_name.cache_clear()
    assert gpu.torch_device() == "cpu"

    try:
        result = score_new_works(demo_frame)
    finally:
        gpu.torch_device.cache_clear()
        gpu.device_name.cache_clear()

    assert len(result) == len(demo_frame)
    assert result["risk_score"].notna().all()
    assert result["risk_score"].between(0, 100).all()
    assert set(result["band"]) <= {"Low", "Medium", "High", "Critical"}
    assert result["reasons_en"].apply(len).min() >= 1
