"""Duplicate works and split-work detection.

**Duplicates.** The same work recorded twice. The earlier implementation chained
four hard gates with AND (cosine, fuzzy ratio, amount ratio, location overlap);
a candidate failing any one was discarded, so a genuine duplicate with a
slightly reworded description or a revised amount was lost. It recalled 5.3% of
planted duplicates.

This version scores every candidate on a weighted blend instead, so strength on
one axis can offset weakness on another:

    pair_score = 0.45*cosine + 0.25*fuzzy + 0.15*location_overlap + 0.15*amount

Candidates come from nearest-neighbour search on the embeddings within the same
district (IDA) or constituency and work type, rather than from all pairs inside
a block, which is both faster and finds matches across constituency boundaries
when the executing district is the same.

The hard part is that similarity alone cannot separate a duplicate from a bulk
rollout, and in fact ranks the rollout higher: fifty byte-identical copies of
"High Mast LED Light" score a perfect 1.0, while a genuinely reworded duplicate
scores about 0.94. Two things fix that. Repetition count is penalised directly,
because two copies of a description in one constituency is a duplicate and fifty
is a programme. And cluster size scales confidence rather than excluding pairs:
discarding oversized clusters outright threw away planted duplicates that had
chained into them, costing 13 points of recall.

**Split works.** One large work broken into several small ones. Vendor identity
is a bonus rather than a requirement here, because vendor is missing for about
20% of works and requiring it discarded most genuine groups.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ml.config import load_config

_TOKEN_RE = re.compile(r"[a-z]{3,}")
_ROUND_UNITS: tuple[float, ...] = (100_000.0, 50_000.0, 25_000.0)


@dataclass
class DuplicateResult:
    """Duplicate pairs, their clusters, and the per-work duplicate score."""

    pairs: pd.DataFrame
    clusters: pd.DataFrame
    dup_score: pd.Series = field(default_factory=lambda: pd.Series(dtype="float64"))
    calibration: dict[str, Any] = field(default_factory=dict)


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

    Anything that is not generic works vocabulary. Village and ward names
    survive; "construction of road" does not.
    """
    return {t for t in _TOKEN_RE.findall(text) if t not in stopwords}


def _standard_descriptions(df: pd.DataFrame, norm: pd.Series, threshold: int) -> frozenset[str]:
    """Descriptions appearing in at least this many distinct constituencies."""
    spread = norm.groupby(norm).apply(lambda s: df.loc[s.index, "constituency"].nunique())
    return frozenset(spread[spread >= threshold].index)


def _candidate_pairs(
    df: pd.DataFrame, embeddings: np.ndarray, cfg: dict[str, Any]
) -> list[tuple[int, int, float]]:
    """Nearest-neighbour candidates within each district/constituency and type.

    Returns positional (i, j, cosine) triples. Blocking on the executing agency
    as well as the constituency lets a duplicate be found when the same district
    records it under either.
    """
    dcfg = cfg["duplicates"]
    k = int(dcfg["neighbours"])
    max_block = int(dcfg["max_block_size"])
    floor = float(dcfg["candidate_cosine_floor"])

    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int, float]] = []

    for key in dcfg["group_keys"]:
        grouped = df.groupby([key, "work_type"], observed=True, sort=False, dropna=True)
        for _, block in grouped:
            n = len(block)
            if n < 2 or n > max_block:
                continue
            rows = block.index.to_numpy()
            vectors = embeddings[rows]
            similarity = vectors @ vectors.T
            np.fill_diagonal(similarity, -1.0)

            take = min(k, n - 1)
            neighbours = np.argpartition(-similarity, kth=take - 1, axis=1)[:, :take]
            for local_i in range(n):
                for local_j in neighbours[local_i]:
                    score = float(similarity[local_i, local_j])
                    if score < floor:
                        continue
                    a, b = int(rows[local_i]), int(rows[int(local_j)])
                    pair = (a, b) if a < b else (b, a)
                    if pair in seen:
                        continue
                    seen.add(pair)
                    out.append((pair[0], pair[1], score))
    return out


def _amount_similarity(a: float, b: float) -> float:
    """1.0 for identical amounts, decaying as the ratio departs from 1."""
    if a <= 0 or b <= 0:
        return 0.0
    ratio = min(a, b) / max(a, b)
    return float(ratio)


def find_duplicates(
    df: pd.DataFrame,
    embeddings: np.ndarray,
    cfg: dict[str, Any] | None = None,
    apply_standard_penalty: bool | None = None,
) -> DuplicateResult:
    """Score duplicate-candidate pairs and collapse the survivors into clusters."""
    cfg = cfg or load_config("ml")
    dcfg = cfg["duplicates"]
    from rapidfuzz import fuzz

    df = df.reset_index(drop=True)
    norm = _normalise(df["work_description"])
    stopwords = frozenset(dcfg["location_stopwords"])
    standard = _standard_descriptions(df, norm, int(dcfg["standard_item_constituencies"]))
    loc_sets = [_location_words(t, stopwords) for t in norm]

    if apply_standard_penalty is None:
        apply_standard_penalty = bool(dcfg["apply_standard_penalty"])

    weights = dcfg["score_weights"]
    threshold = float(dcfg["pair_score_threshold"])
    window = float(dcfg["days_window"])
    penalty = float(dcfg["standard_item_penalty"])
    repeat_free = int(dcfg["repeat_free_copies"])
    repeat_penalty = float(dcfg["repeat_penalty"])

    # How many times does this exact description already appear in this
    # constituency? Two copies is a duplicate; fifty is a rollout. Similarity
    # cannot tell them apart, because a rollout's copies are byte-identical and
    # score a perfect 1.0, while a genuinely reworded duplicate scores lower.
    # Repetition count is the discriminator, so it is penalised explicitly.
    repeat_key = df["constituency"].astype(str) + "||" + norm
    repeat_count = repeat_key.map(repeat_key.value_counts()).to_numpy()

    amounts = pd.to_numeric(df["sanction_amount"], errors="coerce").to_numpy(dtype="float64")
    sanction = pd.to_datetime(df["sanction_date"], errors="coerce").to_numpy(dtype="datetime64[ns]")

    records: list[dict[str, Any]] = []
    for i, j, cosine in _candidate_pairs(df, embeddings, cfg):
        gap = abs((sanction[i] - sanction[j]) / np.timedelta64(1, "D"))
        if not np.isfinite(gap) or gap > window:
            continue

        text_a, text_b = norm.iloc[i], norm.iloc[j]
        fuzzy = fuzz.token_set_ratio(text_a, text_b) / 100.0

        loc_a, loc_b = loc_sets[i], loc_sets[j]
        union = loc_a | loc_b
        shared = loc_a & loc_b
        overlap = len(shared) / len(union) if union else 0.0

        amount_sim = _amount_similarity(amounts[i], amounts[j])

        score = (
            float(weights["cosine"]) * cosine
            + float(weights["fuzzy"]) * fuzzy
            + float(weights["location"]) * overlap
            + float(weights["amount"]) * amount_sim
        )

        is_standard = text_a in standard or text_b in standard
        if is_standard and apply_standard_penalty:
            score -= penalty

        copies = int(max(repeat_count[i], repeat_count[j]))
        if copies > repeat_free:
            score -= repeat_penalty * np.log1p(copies - repeat_free)

        if score < threshold:
            continue

        records.append(
            {
                "work_id_a": df.at[i, "work_id"],
                "work_id_b": df.at[j, "work_id"],
                "constituency": df.at[i, "constituency"],
                "ida": df.at[i, "ida"],
                "work_type": df.at[i, "work_type"],
                "cosine": round(float(cosine), 4),
                "token_set": round(fuzzy * 100, 2),
                "location_overlap": round(float(overlap), 4),
                "amount_similarity": round(float(amount_sim), 4),
                "days_apart": float(gap),
                "amount_a": float(amounts[i]),
                "amount_b": float(amounts[j]),
                "is_standard_item": bool(is_standard),
                "copies_in_constituency": copies,
                "shared_location_words": " ".join(sorted(shared)),
                "pair_score": round(float(score), 4),
            }
        )

    columns = [
        "work_id_a",
        "work_id_b",
        "constituency",
        "ida",
        "work_type",
        "cosine",
        "token_set",
        "location_overlap",
        "amount_similarity",
        "days_apart",
        "amount_a",
        "amount_b",
        "is_standard_item",
        "shared_location_words",
        "pair_score",
    ]
    pairs = pd.DataFrame.from_records(records, columns=columns)
    if pairs.empty:
        return DuplicateResult(
            pairs=pairs,
            clusters=pd.DataFrame(),
            dup_score=pd.Series(0.0, index=df.index, name="dup_score"),
        )

    clusters = _build_clusters(pairs, df)

    # Large clusters are bulk rollouts rather than double entry, but DISCARDING
    # them cost 13 points of recall: a planted duplicate that happened to chain
    # into a big component was thrown away with it. Every pair is kept instead,
    # and confidence is scaled down by the size of the component it sits in, so
    # the same similarity inside a 2-work cluster outranks it inside a 40-work
    # rollout.
    max_cluster = int(dcfg["max_cluster_size"])
    floor = float(dcfg["oversized_cluster_floor"])

    size_by_work: dict[str, int] = {}
    for ids, size in zip(clusters["work_ids"], clusters["n_works"], strict=True):
        for work_id in str(ids).split(","):
            size_by_work[work_id] = int(size)

    sizes = np.maximum(
        pairs["work_id_a"].map(size_by_work).fillna(2).to_numpy(dtype="float64"),
        pairs["work_id_b"].map(size_by_work).fillna(2).to_numpy(dtype="float64"),
    )
    confidence = np.clip(max_cluster / np.maximum(sizes, 1.0), floor, 1.0)

    # Rescale the surviving score across [threshold, 1] so the signal uses its
    # full range. Straight pair_score has almost no dynamic range once the
    # threshold is applied: every kept pair sits between 0.88 and 1.0, which
    # leaves ~18,000 works effectively tied and unable to compete for a place in
    # the top of the ranking, however confident the match.
    spread = (pairs["pair_score"].to_numpy() - threshold) / max(1e-9, 1.0 - threshold)
    pairs["cluster_size"] = sizes.astype(int)
    pairs["cluster_confidence"] = confidence.round(4)
    pairs["dup_confidence"] = (np.clip(spread, 0.0, 1.0) * confidence).round(4)

    return DuplicateResult(pairs=pairs, clusters=clusters, dup_score=_score_works(pairs, df))


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
                pairs[["work_id_a", "dup_confidence"]].rename(columns={"work_id_a": "work_id"}),
                pairs[["work_id_b", "dup_confidence"]].rename(columns={"work_id_b": "work_id"}),
            ]
        )
        .groupby("work_id")["dup_confidence"]
        .max()
    )
    return df["work_id"].map(best).fillna(0.0).rename("dup_score").set_axis(df.index)


# ---------------------------------------------------------------------------
# Split works
# ---------------------------------------------------------------------------


def _just_below_round(amount: float, tolerance: float) -> bool:
    """Does the amount sit just under a round threshold, as a dodge would?"""
    for unit in _ROUND_UNITS:
        if amount <= 0 or amount >= unit * 20:
            continue
        remainder = amount % unit
        if remainder >= unit * (1.0 - tolerance):
            return True
    return False


def fit_split_peer_stats(peered: pd.DataFrame, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Peer median and p90 per peer group, fitted on the training corpus.

    Saved so that scoring an upload judges "below the median" and "jointly above
    the 90th percentile" against the national picture. Computed from a 13-row
    upload instead, the median is whatever those 13 rows happen to be, which is
    why four split road pieces were reported as duplicates rather than a split.
    """
    cfg = cfg or load_config("ml")
    pct = float(cfg["duplicates"]["split_works"]["combined_percentile"])
    amount = pd.to_numeric(peered["sanction_amount"], errors="coerce").astype("float64")
    grouped = amount.groupby(peered["peer_group"].astype(str))
    fine = peered["work_type"].astype(str) + " | " + peered["state"].astype(str)
    return {
        "median": {str(k): float(v) for k, v in grouped.median().items()},
        "p90": {str(k): float(v) for k, v in grouped.quantile(pct / 100.0).items()},
        "fine_counts": {str(k): int(v) for k, v in fine.value_counts().items()},
        "min_group": int(cfg["features"]["peer_min_group"]),
        "fitted_on_rows": int(len(peered)),
    }


def peer_groups_from_stats(df: pd.DataFrame, stats: dict[str, Any]) -> pd.Series:
    """Assign peer groups exactly as training did, using the saved group sizes."""
    fine = df["work_type"].astype(str) + " | " + df["state"].astype(str)
    coarse = df["work_type"].astype(str) + " | ALL-INDIA"
    counts = fine.map(stats["fine_counts"]).fillna(0)
    return pd.Series(
        np.where(counts >= int(stats["min_group"]), fine, coarse), index=df.index, name="peer_group"
    )


def find_split_works(
    df: pd.DataFrame,
    cfg: dict[str, Any] | None = None,
    peer_stats: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Find groups of small works that look like one large work broken up.

    Same district and work type, overlapping location words, sanctioned inside a
    short window, each below the peer median, jointly above the peer 90th
    percentile. A shared vendor raises the score but is not required: vendor is
    missing for about 20% of works and demanding it discarded most groups.

    ``peer_stats`` supplies saved training medians and p90s. Without it they are
    computed from ``df``, which is right for the full corpus and wrong for a
    small upload.
    """
    cfg = cfg or load_config("ml")
    dcfg = cfg["duplicates"]
    scfg = dcfg["split_works"]

    min_group = int(scfg["min_group"])
    max_group = int(scfg["max_group"])
    window = int(scfg["days_window"])
    pct = float(scfg["combined_percentile"])
    median_multiple = float(scfg["combined_median_multiple"])
    min_overlap = float(scfg["min_location_overlap"])
    tolerance = float(scfg["round_threshold_tolerance"])

    work = df.reset_index(drop=True).copy()
    if work.empty:
        return pd.DataFrame()

    amount = pd.to_numeric(work["sanction_amount"], errors="coerce").astype("float64")
    if peer_stats is not None:
        peer = peer_groups_from_stats(work, peer_stats)
        # A peer group training never saw has no median to compare against, so
        # its works cannot be judged "below the median" and drop out below.
        work["_peer_median"] = peer.map(peer_stats["median"]).astype("float64")
        work["_peer_p90"] = peer.map(peer_stats["p90"]).astype("float64")
    else:
        peer = work["peer_group"] if "peer_group" in work.columns else work["work_type"].astype(str)
        work["_peer_median"] = amount.groupby(peer).transform("median")
        work["_peer_p90"] = amount.groupby(peer).transform(lambda s: s.quantile(pct / 100.0))

    stopwords = frozenset(dcfg["location_stopwords"])
    norm = _normalise(work["work_description"])
    loc_sets = [_location_words(t, stopwords) for t in norm]

    rows: list[dict[str, Any]] = []
    for (ida, wtype), block in work.groupby(["ida", "work_type"], observed=True, sort=False):
        if len(block) < min_group:
            continue
        # Keep only the below-median works BEFORE sliding the window. The window
        # spans a contiguous run of dates, so an ordinary large work sanctioned
        # between two pieces of a split would otherwise break the run and hide
        # the group. Small works are what a split is made of; a big neighbour is
        # irrelevant to whether they form one.
        block = block.loc[
            block["sanction_amount"].astype("float64") < block["_peer_median"].astype("float64")
        ]
        if len(block) < min_group:
            continue
        block = block.sort_values("sanction_date", kind="stable")
        positions = block.index.to_numpy()
        dates = pd.to_datetime(block["sanction_date"]).to_numpy()
        amounts = block["sanction_amount"].to_numpy(dtype="float64")
        median = float(block["_peer_median"].iloc[0])
        # Clear the EASIER of the two bars; see configs/ml.yaml for why p90
        # alone is unsatisfiable in heavy-tailed peer groups.
        p90 = min(float(block["_peer_p90"].iloc[0]), median_multiple * median)

        start = 0
        for end in range(len(block)):
            while (dates[end] - dates[start]) / np.timedelta64(1, "D") > window:
                start += 1
            if end + 1 - start > max_group:
                start = end + 1 - max_group
            size = end + 1 - start
            if size < min_group:
                continue
            span = slice(start, end + 1)
            total = float(amounts[span].sum())
            if total <= p90:
                continue

            members = block.iloc[span]
            member_pos = positions[span]
            shared = set(loc_sets[member_pos[0]])
            for pos in member_pos[1:]:
                shared &= loc_sets[pos]
            union: set[str] = set()
            for pos in member_pos:
                union |= loc_sets[pos]
            overlap = len(shared) / len(union) if union else 0.0
            if overlap < min_overlap:
                continue

            vendors = members["vendor_name"].dropna().unique()
            same_vendor = len(vendors) == 1 and len(members["vendor_name"].dropna()) == size
            span_days = float((dates[end] - dates[start]) / np.timedelta64(1, "D"))
            just_below = float(np.mean([_just_below_round(a, tolerance) for a in amounts[span]]))

            rows.append(
                {
                    "ida": str(ida),
                    "work_type": str(wtype),
                    "vendor_name": str(vendors[0]) if same_vendor else "",
                    "same_vendor": bool(same_vendor),
                    "n_works": int(size),
                    "work_ids": ",".join(members["work_id"].astype(str)),
                    "total_amount": total,
                    "peer_median": float(members["_peer_median"].iloc[0]),
                    "peer_p90": p90,
                    "total_vs_p90": round(total / p90, 3) if p90 else 0.0,
                    "span_days": span_days,
                    "location_overlap": round(overlap, 3),
                    "share_just_below_round": round(just_below, 3),
                    "first_sanction": pd.Timestamp(dates[start]),
                    "last_sanction": pd.Timestamp(dates[end]),
                    "constituency": str(members["constituency"].iloc[0]),
                }
            )

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)
    out["split_score"] = _score_splits(out, scfg)

    # The sliding window emits many overlapping spans per district. Keep the
    # best-scoring ones greedily, skipping any group that reuses a work already
    # claimed. Deduplicating by (ida, work_type) instead, as an earlier version
    # did, kept only ONE group per district and silently discarded every other
    # genuine group there.
    out = out.sort_values(["split_score", "n_works"], ascending=False, kind="stable")
    claimed: set[str] = set()
    keep: list[int] = []
    for position, ids in zip(out.index, out["work_ids"], strict=True):
        members = set(str(ids).split(","))
        if members & claimed:
            continue
        claimed |= members
        keep.append(position)

    out = out.loc[keep].reset_index(drop=True)
    out.insert(0, "split_group_id", [f"SPL{i:05d}" for i in range(1, len(out) + 1)])
    return out


def _score_splits(groups: pd.DataFrame, scfg: dict[str, Any]) -> pd.Series:
    """0-1 score: more works, bigger relative total, tighter dates, rounder amounts."""
    weights = scfg["score_weights"]
    window = float(scfg["days_window"])

    # Measured: saturating these terms sooner (size over 3..5, total over
    # 1.0..1.5) looked more principled but scored WORSE, 41.2% detector recall
    # against 46.0%. Changing the score changes the greedy non-overlapping
    # selection, so a group that reads as "better" can displace two that were
    # each right. Kept at the measured-best setting.
    size_term = ((groups["n_works"] - 3) / max(1.0, float(scfg["max_group"]) - 3)).clip(0, 1)
    total_term = ((groups["total_vs_p90"] - 1.0) / 2.0).clip(0, 1)
    tight_term = (1.0 - groups["span_days"] / max(1.0, window)).clip(0, 1)
    round_term = groups["share_just_below_round"].clip(0, 1)
    vendor_term = groups["same_vendor"].astype("float64")

    score = (
        float(weights["size"]) * size_term
        + float(weights["total"]) * total_term
        + float(weights["tight_dates"]) * tight_term
        + float(weights["round_amounts"]) * round_term
        + float(weights["same_vendor"]) * vendor_term
    )
    return score.clip(0.0, 1.0).round(4)


def split_membership(df: pd.DataFrame, splits: pd.DataFrame) -> pd.Series:
    """Per-work split score: the score of the group it belongs to, else 0."""
    if splits.empty:
        return pd.Series(0.0, index=df.index, name="split_score")
    scores: dict[str, float] = {}
    for ids, score in zip(splits["work_ids"], splits["split_score"], strict=True):
        for work_id in str(ids).split(","):
            scores[work_id] = max(scores.get(work_id, 0.0), float(score))
    return df["work_id"].map(scores).fillna(0.0).rename("split_score").set_axis(df.index)
