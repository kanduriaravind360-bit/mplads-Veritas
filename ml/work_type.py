"""Derive a usable work type from the free-text work description.

The dataset's own ``work_category`` is 97.7% "Normal/Others", so it cannot serve
as a peer group for cost comparison. This module replaces it with a type derived
from the description itself:

1. Ordered keyword/regex rules (English plus common Hinglish spellings) cover
   the bulk of the corpus. First match wins, so specific types are listed before
   the broader ones that would otherwise swallow them.
2. Whatever no rule matches is embedded with a multilingual sentence
   transformer on the GPU, clustered with KMeans, and each cluster is named from
   its top TF-IDF terms.

All patterns and thresholds live in ``configs/ml.yaml``.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.config import load_config, resolve
from ml.gpu import torch_device


def compile_rules(cfg: dict[str, Any]) -> list[tuple[str, re.Pattern[str]]]:
    """Compile the ordered work-type rules from config."""
    return [
        (rule["name"], re.compile(rule["pattern"], re.IGNORECASE))
        for rule in cfg["work_type"]["rules"]
    ]


def apply_rules(descriptions: pd.Series, cfg: dict[str, Any] | None = None) -> pd.Series:
    """Label each description with the first matching rule, else NA.

    Matching is done rule-by-rule over the whole column rather than row-by-row,
    which is far faster on 77k rows, and assigns only rows still unlabelled so
    that earlier (more specific) rules keep priority.
    """
    cfg = cfg or load_config("ml")
    rules = compile_rules(cfg)
    text = descriptions.fillna("").astype(str)
    out = pd.Series(pd.NA, index=descriptions.index, dtype="object")

    for name, pattern in rules:
        todo = out.isna()
        if not todo.any():
            break
        hit = text[todo].str.contains(pattern, na=False)
        out.loc[hit[hit].index] = name
    return out


SEPARATOR = bytes([0])


def _corpus_digest(descriptions: pd.Series) -> str:
    """Short stable hash of a description corpus, used to key the cache."""
    hasher = hashlib.blake2b(digest_size=8)
    hasher.update(str(len(descriptions)).encode())
    for text in descriptions.fillna("").astype(str):
        hasher.update(text.encode("utf-8", "ignore"))
        hasher.update(SEPARATOR)
    return hasher.hexdigest()


def embed_descriptions(
    descriptions: pd.Series,
    cfg: dict[str, Any] | None = None,
    cache_path: Path | str | None = None,
    use_cache: bool = True,
) -> np.ndarray:
    """Embed descriptions with a multilingual sentence transformer on the GPU.

    Embeddings are cached to ``data/processed/embeddings.npy``. The cache is
    reused only when its row count matches, so a changed corpus recomputes.
    """
    cfg = cfg or load_config("ml")
    ecfg = cfg["embeddings"]
    base = Path(cache_path) if cache_path else resolve(cfg["paths"]["embeddings"])

    # Key the cache on the CONTENT of the corpus, not just its row count. The
    # injection test embeds a different corpus (the real works plus planted
    # rows); with a single fixed filename it overwrote the main cache, and the
    # main run then silently fell back to no embeddings at all.
    digest = _corpus_digest(descriptions)
    path = base.with_name(f"{base.stem}-{digest}{base.suffix}")

    if use_cache and path.exists():
        cached = np.load(path)
        if cached.shape[0] == len(descriptions):
            return cached

    from sentence_transformers import SentenceTransformer

    device = torch_device()
    model = SentenceTransformer(ecfg["model_name"], device=device)
    model.max_seq_length = int(ecfg["max_seq_length"])

    vectors = model.encode(
        descriptions.fillna("").astype(str).tolist(),
        batch_size=int(ecfg["batch_size"]),
        convert_to_numpy=True,
        normalize_embeddings=bool(ecfg["normalize"]),
        show_progress_bar=False,
    ).astype("float32")

    if use_cache:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, vectors)
    return vectors


def _name_clusters(texts: list[str], labels: np.ndarray, cfg: dict[str, Any]) -> dict[int, str]:
    """Name each cluster from the highest-weight TF-IDF terms of its members."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    fcfg = cfg["work_type"]["fallback"]
    joined = [
        " ".join(t for t, lab in zip(texts, labels, strict=True) if lab == c)
        for c in sorted(set(labels.tolist()))
    ]
    vec = TfidfVectorizer(
        max_features=int(fcfg["max_features"]),
        min_df=1,
        stop_words="english",
        token_pattern=r"[A-Za-z]{3,}",
    )
    matrix = vec.fit_transform(joined)
    vocab = np.array(vec.get_feature_names_out())
    n_terms = int(fcfg["name_terms"])
    prefix = str(fcfg["label_prefix"])

    names: dict[int, str] = {}
    for row, cluster in enumerate(sorted(set(labels.tolist()))):
        weights = matrix[row].toarray().ravel()
        if weights.sum() == 0:
            names[cluster] = f"{prefix}misc"
            continue
        top = vocab[np.argsort(-weights)[:n_terms]]
        names[cluster] = prefix + " ".join(top)
    return names


def cluster_unmatched(
    descriptions: pd.Series,
    embeddings: np.ndarray,
    cfg: dict[str, Any] | None = None,
) -> pd.Series:
    """Cluster rule-unmatched descriptions and label each with its TF-IDF name."""
    cfg = cfg or load_config("ml")
    fcfg = cfg["work_type"]["fallback"]
    seed = int(cfg["seed"])

    if len(descriptions) == 0:
        return pd.Series(dtype="object")

    n_clusters = min(int(fcfg["n_clusters"]), len(descriptions))
    if n_clusters < 2:
        return pd.Series(
            cfg["work_type"]["unmatched_label"], index=descriptions.index, dtype="object"
        )

    from sklearn.cluster import KMeans

    km = KMeans(n_clusters=n_clusters, random_state=seed, n_init=10)
    labels = km.fit_predict(embeddings)

    texts = descriptions.fillna("").astype(str).tolist()
    names = _name_clusters(texts, labels, cfg)
    return pd.Series([names[int(v)] for v in labels], index=descriptions.index, dtype="object")


def assign_work_type(
    df: pd.DataFrame,
    cfg: dict[str, Any] | None = None,
    embeddings: np.ndarray | None = None,
    use_embeddings: bool = True,
) -> pd.Series:
    """Return a ``work_type`` label for every row.

    Rules first; anything left over is clustered on its embedding. With
    ``use_embeddings=False`` the leftovers collapse to the configured
    ``unmatched_label`` instead, which keeps tests fast and offline.
    """
    cfg = cfg or load_config("ml")
    types = apply_rules(df["work_description"], cfg)
    unmatched = types.isna()

    if not unmatched.any():
        return types.astype("object")

    if not use_embeddings:
        types.loc[unmatched] = cfg["work_type"]["unmatched_label"]
        return types.astype("object")

    if embeddings is None:
        embeddings = embed_descriptions(df["work_description"], cfg)

    positions = np.flatnonzero(unmatched.to_numpy())
    sub = df.loc[unmatched, "work_description"]
    types.loc[unmatched] = cluster_unmatched(sub, embeddings[positions], cfg).to_numpy()
    return types.astype("object")


def work_type_counts(types: pd.Series) -> pd.DataFrame:
    """Counts and shares per work type, most common first."""
    counts = types.value_counts()
    return pd.DataFrame(
        {
            "work_type": counts.index,
            "works": counts.to_numpy(),
            "share_pct": (counts / len(types) * 100).round(2).to_numpy(),
        }
    )
