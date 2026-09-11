"""Duplicate works and split-work detection.

Two distinct patterns, both of which a reviewer can check directly:

**Duplicates.** The same work described twice in the same area. Candidate pairs
must share a constituency (or IDA) and a work type, be close in both embedding
space and token overlap, be sanctioned within a couple of years of each other,
and be of comparable value.

The hard part is that most repeated descriptions are innocent. "High Mast LED
Light" is a standard catalogue item ordered in hundreds of places. So a
description appearing across many different constituencies is treated as a
standard item and a pair of them survives only if it *also* shares a location
word, which is what distinguishes "a light in Rampur" from "a light somewhere".

**Split works.** One large work broken into several small ones to stay under a
sanction threshold. We look for several works from the same IDA, vendor and
type, sanctioned within a short window, each individually below the peer median
but jointly above the peer 90th percentile.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ml.config import load_config

_TOKEN_RE = re.compile(r"[a-z]{3,}")


@dataclass
class DuplicateResult:
    """Duplicate pairs, their clusters, and the per-work duplicate score."""

    pairs: pd.DataFrame
    clusters: pd.DataFrame
    dup_score: pd.Series = field(default_factory=lambda: pd.Series(dtype="float64"))


def _normalise(text: pd.Series) -> pd.Series:
    return (
        text.fillna("")
        .astype(str)
        .str.lower()
        .str.replace(r"[^a-z0-9\s]", " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )


def _location_words(text: str, stopwords: frozenset[str]) -> set[str]:
    """Content words that plausibly name a place.

    Crude but effective: anything that is not a generic works-vocabulary term.
    Village and ward names survive; "construction of road" does not.
    """
    return {t for t in _TOKEN_RE.findall(text) if t not in stopwords}


def _standard_descriptions(df: pd.DataFrame, norm: pd.Series, threshold: int) -> frozenset[str]:
    """Descriptions that appear in this many or more distinct constituencies."""
    spread = norm.groupby(norm).apply(lambda s: df.loc[s.index, "constituency"].nunique())
    return frozenset(spread[spread >= threshold].index)


def find_duplicates(
    df: pd.DataFrame,
    embeddings: np.ndarray,
    cfg: dict[str, Any] | None = None,
) -> DuplicateResult:
    """Find duplicate-candidate pairs and collapse them into clusters."""
    cfg = cfg or load_config("ml")
    dcfg = cfg["duplicates"]
    from rapidfuzz import fuzz

    norm = _normalise(df["work_description"])
    stopwords = frozenset(dcfg["location_stopwords"])
    standard = _standard_descriptions(df, norm, int(dcfg["standard_item_constituencies"]))

    cos_min = float(dcfg["cosine_min"])
    fuzzy_min = float(dcfg["fuzzy_min"])
    window = float(dcfg["days_window"])
    ratio_lo = float(dcfg["amount_ratio_min"])
    ratio_hi = float(dcfg["amount_ratio_max"])
    max_block = int(dcfg["max_block_size"])
    min_jaccard = float(dcfg["min_location_jaccard"])
    standard_jaccard = float(dcfg["standard_item_jaccard"])

    positions = {work_id: i for i, work_id in enumerate(df["work_id"].to_numpy())}
    amounts = pd.to_numeric(df["sanction_amount"], errors="coerce").to_numpy(dtype="float64")
    # Coerce rather than assume: an uploaded CSV (score_new_works) can arrive
    # with dates as strings or as an object column.
    sanction = pd.to_datetime(df["sanction_date"], errors="coerce").to_numpy(dtype="datetime64[ns]")
    loc_sets = [_location_words(t, stopwords) for t in norm]

    records: list[dict[str, Any]] = []
    primary = dcfg["group_keys"][0]

    for _, block in df.groupby([primary, "work_type"], observed=True, sort=False):
        if len(block) < 2 or len(block) > max_block:
            continue
        idx = block.index.to_numpy()
        rows = np.array([positions[w] for w in block["work_id"]])
        vecs = embeddings[rows]
        sim = vecs @ vecs.T

        ii, jj = np.triu_indices(len(idx), k=1)
        keep = sim[ii, jj] >= cos_min
        if not keep.any():
            continue
        ii, jj = ii[keep], jj[keep]

        # Vectorise the cheap numeric gates. Only survivors reach the per-pair
        # set and string comparisons, which dominate the runtime.
        ra_all, rb_all = rows[ii], rows[jj]
        gaps = np.abs((sanction[ra_all] - sanction[rb_all]) / np.timedelta64(1, "D"))
        amt_a_all, amt_b_all = amounts[ra_all], amounts[rb_all]
        with np.errstate(divide="ignore", invalid="ignore"):
            ratios = amt_a_all / amt_b_all
        ok = (
            np.isfinite(gaps)
            & (gaps <= window)
            & (amt_a_all > 0)
            & (amt_b_all > 0)
            & (
                ((ratios >= ratio_lo) & (ratios <= ratio_hi))
                | ((1 / ratios >= ratio_lo) & (1 / ratios <= ratio_hi))
            )
        )
        for a, b, gap, amt_a, amt_b in zip(
            ii[ok], jj[ok], gaps[ok], amt_a_all[ok], amt_b_all[ok], strict=True
        ):
            a, b = int(a), int(b)
            ia, ib = idx[a], idx[b]
            ra, rb = rows[a], rows[b]
            gap = float(gap)

            text_a, text_b = norm.iloc[ra], norm.iloc[rb]

            # Location gate first: it is a cheap set operation and rejects the
            # overwhelming majority of bulk-rollout pairs before the much more
            # expensive fuzzy string comparison runs.
            loc_a, loc_b = loc_sets[ra], loc_sets[rb]
            union = loc_a | loc_b
            shared = loc_a & loc_b
            jaccard = len(shared) / len(union) if union else 0.0
            is_standard = text_a in standard or text_b in standard
            if jaccard < (standard_jaccard if is_standard else min_jaccard):
                continue

            token_sim = fuzz.token_set_ratio(text_a, text_b)
            if token_sim < fuzzy_min:
                continue

            records.append(
                {
                    "work_id_a": df.at[ia, "work_id"],
                    "work_id_b": df.at[ib, "work_id"],
                    "constituency": df.at[ia, "constituency"],
                    "ida": df.at[ia, "ida"],
                    "work_type": df.at[ia, "work_type"],
                    "cosine": float(sim[a, b]),
                    "token_set": float(token_sim),
                    "days_apart": float(gap),
                    "amount_a": float(amt_a),
                    "amount_b": float(amt_b),
                    "is_standard_item": bool(is_standard),
                    "location_jaccard": float(jaccard),
                    "shared_location_words": " ".join(sorted(shared)),
                }
            )

    pairs = pd.DataFrame.from_records(records)
    if pairs.empty:
        pairs = pd.DataFrame(
            columns=[
                "work_id_a",
                "work_id_b",
                "constituency",
                "ida",
                "work_type",
                "cosine",
                "token_set",
                "days_apart",
                "amount_a",
                "amount_b",
                "is_standard_item",
                "location_jaccard",
                "shared_location_words",
                "pair_score",
            ]
        )
        empty = pd.Series(0.0, index=df.index, name="dup_score")
        return DuplicateResult(pairs=pairs, clusters=pd.DataFrame(), dup_score=empty)

    # Blend the two similarity measures; a pair that is strong on both is a
    # better candidate than one carried by either alone.
    pairs["pair_score"] = 0.5 * ((pairs["cosine"] - cos_min) / max(1e-9, 1 - cos_min)).clip(
        0, 1
    ) + 0.5 * ((pairs["token_set"] - fuzzy_min) / max(1e-9, 100 - fuzzy_min)).clip(0, 1)
    pairs["pair_score"] = 0.5 + 0.5 * pairs["pair_score"]

    clusters = _build_clusters(pairs, df)

    # Drop bulk rollouts: a cluster larger than max_cluster_size is one
    # catalogue item ordered many times, not one work entered many times.
    max_cluster = int(dcfg["max_cluster_size"])
    oversized = clusters.loc[clusters["n_works"] > max_cluster, "work_ids"]
    if not oversized.empty:
        bulk: set[str] = set()
        for ids in oversized:
            bulk.update(str(ids).split(","))
        pairs = pairs.loc[
            ~pairs["work_id_a"].isin(bulk) & ~pairs["work_id_b"].isin(bulk)
        ].reset_index(drop=True)
        clusters = clusters.loc[clusters["n_works"] <= max_cluster].reset_index(drop=True)

    dup_score = _score_works(pairs, df)
    return DuplicateResult(pairs=pairs, clusters=clusters, dup_score=dup_score)


def _build_clusters(pairs: pd.DataFrame, df: pd.DataFrame) -> pd.DataFrame:
    """Collapse duplicate pairs into connected components."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for a, b in zip(pairs["work_id_a"], pairs["work_id_b"], strict=True):
        union(a, b)

    groups: dict[str, list[str]] = {}
    for work_id in parent:
        groups.setdefault(find(work_id), []).append(work_id)

    lookup = df.set_index("work_id")
    rows = []
    for i, (root, members) in enumerate(sorted(groups.items()), start=1):
        members = sorted(members)
        sub = lookup.loc[members]
        rows.append(
            {
                "dup_group_id": f"DUP{i:05d}",
                "n_works": len(members),
                "work_ids": ",".join(members),
                "constituency": str(sub["constituency"].iloc[0]),
                "ida": str(sub["ida"].iloc[0]),
                "work_type": str(sub["work_type"].iloc[0]),
                "total_amount": float(sub["sanction_amount"].sum()),
                "example_description": str(sub["work_description"].iloc[0])[:200],
                "root": root,
            }
        )
    return pd.DataFrame(rows)


def _score_works(pairs: pd.DataFrame, df: pd.DataFrame) -> pd.Series:
    """Per-work duplicate score: the strongest pair each work participates in."""
    best = (
        pd.concat(
            [
                pairs[["work_id_a", "pair_score"]].rename(columns={"work_id_a": "work_id"}),
                pairs[["work_id_b", "pair_score"]].rename(columns={"work_id_b": "work_id"}),
            ]
        )
        .groupby("work_id")["pair_score"]
        .max()
    )
    return df["work_id"].map(best).fillna(0.0).rename("dup_score").set_axis(df.index)


def find_split_works(df: pd.DataFrame, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
    """Find groups of small works that look like one large work broken up.

    Same IDA, vendor and work type, sanctioned inside a short window, each below
    the peer median, jointly above the peer 90th percentile.
    """
    cfg = cfg or load_config("ml")
    scfg = cfg["duplicates"]["split_works"]
    min_group = int(scfg["min_group"])
    max_group = int(scfg["max_group"])
    window = int(scfg["days_window"])
    pct = float(scfg["combined_percentile"])

    work = df.loc[df["vendor_name"].notna()].copy()
    if work.empty:
        return pd.DataFrame()

    amount = work["sanction_amount"].astype("float64")
    peer = work["peer_group"] if "peer_group" in work.columns else work["work_type"].astype(str)
    work["_peer_median"] = amount.groupby(peer).transform("median")
    work["_peer_p90"] = amount.groupby(peer).transform(lambda s: s.quantile(pct / 100.0))

    rows: list[dict[str, Any]] = []
    grouped = work.groupby(["ida", "vendor_name", "work_type"], observed=True, sort=False)
    for (ida, vendor, wtype), block in grouped:
        if len(block) < min_group:
            continue
        block = block.sort_values("sanction_date", kind="stable")
        dates = block["sanction_date"].to_numpy()
        amounts = block["sanction_amount"].to_numpy(dtype="float64")
        below = block["sanction_amount"].to_numpy() < block["_peer_median"].to_numpy()
        p90 = float(block["_peer_p90"].iloc[0])

        start = 0
        for end in range(len(block)):
            while (dates[end] - dates[start]) / np.timedelta64(1, "D") > window:
                start += 1
            # A window wider than max_group is a bulk programme, not a split.
            if end + 1 - start > max_group:
                start = end + 1 - max_group
            span = slice(start, end + 1)
            if end + 1 - start < min_group:
                continue
            if not below[span].all():
                continue
            total = float(amounts[span].sum())
            if total <= p90:
                continue
            members = block.iloc[span]
            rows.append(
                {
                    "ida": str(ida),
                    "vendor_name": str(vendor),
                    "work_type": str(wtype),
                    "n_works": int(end + 1 - start),
                    "work_ids": ",".join(members["work_id"].astype(str)),
                    "total_amount": total,
                    "peer_median": float(members["_peer_median"].iloc[0]),
                    "peer_p90": p90,
                    "first_sanction": pd.Timestamp(dates[start]),
                    "last_sanction": pd.Timestamp(dates[end]),
                    "constituency": str(members["constituency"].iloc[0]),
                }
            )

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)
    # Keep the widest group per (ida, vendor, type) so one split is not reported
    # once per sliding window position.
    out = (
        out.sort_values("n_works", ascending=False)
        .drop_duplicates(subset=["ida", "vendor_name", "work_type"], keep="first")
        .reset_index(drop=True)
    )
    out.insert(0, "split_group_id", [f"SPL{i:05d}" for i in range(1, len(out) + 1)])
    return out


def split_membership(df: pd.DataFrame, splits: pd.DataFrame) -> pd.Series:
    """Boolean series: is this work part of a suspected split group?"""
    if splits.empty:
        return pd.Series(False, index=df.index, name="in_split_group")
    members: set[str] = set()
    for ids in splits["work_ids"]:
        members.update(str(ids).split(","))
    return df["work_id"].isin(members).rename("in_split_group")
