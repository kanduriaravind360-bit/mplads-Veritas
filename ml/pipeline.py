"""The end-to-end scoring pipeline, shared by training and by new data.

:func:`run` executes every stage and returns everything the backend needs.
:func:`score_new_works` reuses the saved artefacts to score an uploaded batch
without retraining, which is what step 3's CSV upload endpoint will call.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml import holdout as holdout_module
from ml.config import load_config, resolve
from ml.data import clean, load_raw
from ml.detect_anomaly import detect
from ml.detect_duplicates import find_duplicates, find_split_works, split_membership
from ml.features import build_features, build_peer_groups, save_feature_list
from ml.gpu import device_name, set_seed, torch_device
from ml.risk import band_for, build_reasons, build_rollups, score
from ml.work_type import assign_work_type, embed_descriptions, work_type_counts


@dataclass
class PipelineResult:
    """Everything one full run produces."""

    scored: pd.DataFrame
    alerts: pd.DataFrame
    rollups: dict[str, pd.DataFrame]
    duplicates: pd.DataFrame
    splits: pd.DataFrame
    metrics: dict[str, Any]
    feature_names: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)


class _Timer:
    """Collects per-stage wall-clock timings for the final summary."""

    def __init__(self) -> None:
        self.timings: dict[str, float] = {}
        self._start = time.perf_counter()

    def stage(self, name: str) -> _StageTimer:
        return _StageTimer(self, name)

    @property
    def total(self) -> float:
        return time.perf_counter() - self._start


class _StageTimer:
    def __init__(self, parent: _Timer, name: str) -> None:
        self.parent = parent
        self.name = name

    def __enter__(self) -> _StageTimer:
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.parent.timings[self.name] = time.perf_counter() - self._t0
        print(f"  [{self.parent.timings[self.name]:6.1f}s] {self.name}", flush=True)


def load_works(cfg: dict[str, Any]) -> pd.DataFrame:
    """Read the cleaned works table, building it from the workbook if absent."""
    path = resolve(cfg["paths"]["works"])
    if path.exists():
        return pd.read_parquet(path)
    data_cfg = load_config("data")
    return clean(load_raw(data_cfg), data_cfg)


def _embed_or_fall_back(descriptions: pd.Series, cfg: dict[str, Any]) -> tuple[np.ndarray, str]:
    """Embed descriptions, degrading rather than crashing.

    Order: a cached corpus (no model needed at all), then the sentence
    transformer, then character TF-IDF. The last is a real downgrade at matching
    reworded duplicates, but a working page beats a stack trace in front of an
    audience, and the caller is told which one was used so it can say so.
    """
    from ml.work_type import (
        EmbeddingModelUnavailableError,
        has_cached_embeddings,
        tfidf_embeddings,
    )

    if has_cached_embeddings(descriptions, cfg):
        return embed_descriptions(descriptions, cfg), "cache"
    try:
        return embed_descriptions(descriptions, cfg), "sentence-transformer"
    except EmbeddingModelUnavailableError as error:
        print(f"  embedding model unavailable ({error}); using TF-IDF instead", flush=True)
        return tfidf_embeddings(descriptions, cfg), "tfidf-fallback"
    except Exception as error:  # noqa: BLE001 - never let this crash a demo
        print(f"  embedding failed ({type(error).__name__}: {error}); using TF-IDF", flush=True)
        return tfidf_embeddings(descriptions, cfg), "tfidf-fallback"


def precompute_demo_embeddings(cfg: dict[str, Any] | None = None) -> dict[str, str]:
    """Warm the embedding cache for the two Live Scoring buttons.

    Both buttons score a fixed corpus, so their embeddings can be computed once
    here and read from disk forever after. That takes the sentence transformer
    out of the demo path entirely: the buttons cannot fail on a model-loading
    problem, because they never load a model.
    """
    cfg = cfg or load_config("ml")
    from ml.data import clean as clean_frame
    from ml.work_type import embed_descriptions

    out: dict[str, str] = {}
    data_cfg = load_config("data")

    demo_csv = resolve("demo_data/live_demo_works.csv")
    if demo_csv.exists():
        demo = pd.read_csv(demo_csv).drop(columns=["demo_key", "expected_outcome"], errors="ignore")
        prepared = clean_frame(demo, data_cfg)
        embed_descriptions(prepared["work_description"], cfg)
        out["demo_works"] = f"{len(prepared)} rows"

    holdout_path = resolve(cfg["paths"]["holdout_works"])
    if holdout_path.exists():
        holdout = pd.read_parquet(holdout_path)
        embed_descriptions(holdout["work_description"], cfg)
        out["holdout_all"] = f"{len(holdout)} rows"
        # The button scores a fixed sample, which is a different corpus and so a
        # different cache key.
        sample = holdout.sample(n=min(100, len(holdout)), random_state=42).reset_index(drop=True)
        embed_descriptions(sample["work_description"], cfg)
        out["holdout_sample_100"] = f"{len(sample)} rows"

    return out


#: Columns split detection needs from the existing corpus when scoring an upload.
_CONTEXT_COLUMNS = (
    "work_id",
    "ida",
    "constituency",
    "state",
    "work_type",
    "work_description",
    "sanction_date",
    "sanction_amount",
    "vendor_name",
)


def _with_corpus_context(works: pd.DataFrame, cfg: dict[str, Any]) -> tuple[pd.DataFrame, set[str]]:
    """The batch plus already-scored works from the same districts.

    Split pieces share a district by definition, so only those districts are
    loaded, which keeps an upload fast. Returns the combined frame and the set of
    batch work ids, so callers can keep only groups that touch the batch.
    """
    batch_ids = set(works["work_id"].astype(str))
    path = resolve(cfg["paths"]["scored_works"])
    if not path.exists():
        return works, batch_ids

    districts = set(works["ida"].astype(str))
    corpus = pd.read_parquet(path, columns=list(_CONTEXT_COLUMNS))
    corpus = corpus.loc[
        corpus["ida"].astype(str).isin(districts) & ~corpus["work_id"].astype(str).isin(batch_ids)
    ]
    if corpus.empty:
        return works, batch_ids

    wanted = [c for c in _CONTEXT_COLUMNS if c in works.columns]
    combined = pd.concat([works[wanted], corpus[wanted]], ignore_index=True)
    combined["sanction_date"] = pd.to_datetime(combined["sanction_date"], errors="coerce")
    return combined, batch_ids


def _split_absorbs(duplicates: pd.DataFrame, splits: pd.DataFrame) -> dict[str, str]:
    """Duplicate clusters lying wholly inside one split group, mapped to that group."""
    if duplicates.empty or splits.empty:
        return {}
    groups = [
        (gid, set(str(ids).split(",")))
        for gid, ids in zip(splits["split_group_id"], splits["work_ids"], strict=True)
    ]
    absorbed: dict[str, str] = {}
    for dup_id, ids in zip(duplicates["dup_group_id"], duplicates["work_ids"], strict=True):
        members = set(str(ids).split(","))
        for gid, split_members in groups:
            if members <= split_members:
                absorbed[str(dup_id)] = str(gid)
                break
    return absorbed


def _split_alert_reasons(row: pd.Series, similarity: dict[str, float], lang: str) -> list[str]:
    """Name the split pattern first; description similarity only as support."""
    from ml.risk import format_inr

    n = int(row["n_works"])
    total = format_inr(float(row["total_amount"]))
    days = float(row.get("span_days") or 0.0)
    same_vendor = bool(row.get("same_vendor", False))
    sim = similarity.get(str(row["split_group_id"]))

    if lang == "hi":
        who = "एक ही विक्रेता को " if same_vendor else "इसी जिले में "
        out = [
            f"संभावित विभाजित कार्य: {who}{days:.0f} दिनों में {n} कार्य, कुल {total}, "
            "प्रत्येक समकक्ष मध्यमान से कम"
        ]
        if sim is not None:
            out.append(f"सहायक साक्ष्य: इन कार्यों के विवरण {sim:.0%} तक समान हैं")
        return out

    who = "to the same vendor" if same_vendor else "in the same district"
    out = [
        f"Possible split work: {n} works {who} within {days:.0f} days, "
        f"together {total}, each below the peer median"
    ]
    if sim is not None:
        out.append(f"Supporting evidence: the descriptions are up to {sim:.0%} similar")
    return out


def build_alerts(
    scored: pd.DataFrame,
    duplicates: pd.DataFrame,
    splits: pd.DataFrame,
    cfg: dict[str, Any],
    dup_pairs: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Assemble the review queue: high-risk works plus duplicate and split groups.

    A duplicate cluster that sits wholly inside a split group is not raised as
    its own alert. Split pieces usually share near-identical wording, so the
    similarity is evidence FOR the split, and reporting both would send a
    reviewer the same works twice under two different stories.
    """
    bands = set(cfg["risk"]["alert_bands"])
    rows: list[pd.DataFrame] = []

    absorbed = _split_absorbs(duplicates, splits)
    if absorbed:
        duplicates = duplicates.loc[~duplicates["dup_group_id"].astype(str).isin(absorbed)]

    # Highest description similarity among each split group's own pieces.
    split_similarity: dict[str, float] = {}
    if dup_pairs is not None and not dup_pairs.empty and not splits.empty:
        for gid, ids in zip(splits["split_group_id"], splits["work_ids"], strict=True):
            members = set(str(ids).split(","))
            inside = dup_pairs["work_id_a"].isin(members) & dup_pairs["work_id_b"].isin(members)
            if inside.any():
                split_similarity[str(gid)] = float(dup_pairs.loc[inside, "pair_score"].max())

    flagged = scored.loc[scored["band"].isin(bands)].copy()
    if not flagged.empty:
        rows.append(
            pd.DataFrame(
                {
                    "alert_id": flagged["work_id"].astype(str),
                    "alert_type": "high_risk_work",
                    "severity": flagged["band"],
                    "risk_score": flagged["risk_score"],
                    "work_ids": flagged["work_id"].astype(str),
                    "n_works": 1,
                    "state": flagged["state"].astype(str),
                    "ida": flagged["ida"].astype(str),
                    "constituency": flagged["constituency"].astype(str),
                    "work_type": flagged["work_type"].astype(str),
                    "amount": flagged["sanction_amount"],
                    "reasons_en": flagged["reasons_en"],
                    "reasons_hi": flagged["reasons_hi"],
                }
            )
        )

    if not duplicates.empty:
        rows.append(
            pd.DataFrame(
                {
                    "alert_id": duplicates["dup_group_id"],
                    "alert_type": "duplicate_group",
                    "severity": np.where(duplicates["n_works"] >= 3, "High", "Medium"),
                    "risk_score": np.nan,
                    "work_ids": duplicates["work_ids"],
                    "n_works": duplicates["n_works"],
                    "state": "",
                    "ida": duplicates["ida"].astype(str),
                    "constituency": duplicates["constituency"].astype(str),
                    "work_type": duplicates["work_type"].astype(str),
                    "amount": duplicates["total_amount"],
                    "reasons_en": [
                        [f"{n} near-identical works in the same constituency totalling {a:,.0f}"]
                        for n, a in zip(
                            duplicates["n_works"], duplicates["total_amount"], strict=True
                        )
                    ],
                    "reasons_hi": [
                        [f"एक ही निर्वाचन क्षेत्र में {n} लगभग समान कार्य, कुल {a:,.0f}"]
                        for n, a in zip(
                            duplicates["n_works"], duplicates["total_amount"], strict=True
                        )
                    ],
                }
            )
        )

    if not splits.empty:
        rows.append(
            pd.DataFrame(
                {
                    "alert_id": splits["split_group_id"],
                    "alert_type": "split_work_group",
                    "severity": "High",
                    "risk_score": np.nan,
                    "work_ids": splits["work_ids"],
                    "n_works": splits["n_works"],
                    "state": "",
                    "ida": splits["ida"].astype(str),
                    "constituency": splits["constituency"].astype(str),
                    "work_type": splits["work_type"].astype(str),
                    "amount": splits["total_amount"],
                    "reasons_en": [
                        _split_alert_reasons(row, split_similarity, "en")
                        for _, row in splits.iterrows()
                    ],
                    "reasons_hi": [
                        _split_alert_reasons(row, split_similarity, "hi")
                        for _, row in splits.iterrows()
                    ],
                }
            )
        )

    if not rows:
        return pd.DataFrame()
    alerts = pd.concat(rows, ignore_index=True)
    return alerts.sort_values(
        ["severity", "risk_score"], ascending=[True, False], kind="stable"
    ).reset_index(drop=True)


def run(
    cfg: dict[str, Any] | None = None,
    df: pd.DataFrame | None = None,
    use_embeddings: bool = True,
    train_models: bool = True,
    save: bool = True,
    apply_holdout: bool = True,
) -> PipelineResult:
    """Run every stage end to end.

    ``use_embeddings=False`` skips the sentence transformer, which makes tests
    fast and offline at the cost of the clustered work-type fallback.
    """
    cfg = cfg or load_config("ml")
    set_seed(int(cfg["seed"]))
    timer = _Timer()
    metrics: dict[str, Any] = {
        "device": {"torch": torch_device(), "name": device_name()},
        "seed": int(cfg["seed"]),
    }

    with timer.stage("load works"):
        works = load_works(cfg) if df is None else df.copy()
        works = works.reset_index(drop=True)

        # Reserve the holdout BEFORE anything is fitted or any statistic is
        # computed. Everything downstream, including peer medians and district
        # history, then sees the training portion only. Skipped when the caller
        # supplies its own frame, because that is a scoring run, not a fit.
        if df is None and apply_holdout and holdout_module.is_enabled(cfg):
            split = holdout_module.split(works, cfg)
            works = split.train
            if save:
                holdout_module.save(split.holdout, cfg)
                holdout_module.write_config(split.constituencies, split.checks, cfg)
            metrics["holdout"] = {
                **split.checks,
                "constituencies_file": "configs/holdout.yaml",
                "excluded_from": [
                    "expected-cost model",
                    "delay model",
                    "proxy-label model",
                    "isolation forest and ECOD",
                    "peer group medians and MADs",
                    "vendor, district and constituency statistics",
                    "duplicate and split-work candidate generation",
                ],
            }
            print(
                f"  holdout: {len(split.holdout):,} works across "
                f"{len(split.constituencies)} constituencies held out before fitting",
                flush=True,
            )

    models: dict[str, Any] = {}
    embeddings: np.ndarray | None = None
    if use_embeddings:
        with timer.stage("embed descriptions (GPU)"):
            embeddings, embedding_source = _embed_or_fall_back(works["work_description"], cfg)
            metrics["embedding_source"] = embedding_source

    with timer.stage("work type"):
        works["work_type"] = assign_work_type(
            works, cfg, embeddings=embeddings, use_embeddings=use_embeddings
        )
        counts = work_type_counts(works["work_type"])
        metrics["work_type"] = {
            "n_types": int(works["work_type"].nunique()),
            "counts": counts.head(15).to_dict("records"),
        }

    with timer.stage("quantity + expected cost"):
        from ml.expected_cost import fit_predict
        from ml.quantity import add_unit_rates, coverage, extract

        quantities = add_unit_rates(works, extract(works["work_description"]), cfg)
        metrics["quantity_extraction"] = coverage(quantities)

        cost_artifacts_path = resolve(cfg["paths"]["models_dir"]) / "expected_cost.joblib"
        if not train_models and cost_artifacts_path.exists():
            # Scoring run: price against the TRAINING model, never against the
            # batch itself.
            import joblib

            from ml.expected_cost import apply_saved

            cost = apply_saved(works, quantities, embeddings, joblib.load(cost_artifacts_path), cfg)
        else:
            cost = fit_predict(works, quantities, embeddings, cfg)
            models["expected_cost"] = cost.artifacts
        works["quantity"] = quantities["quantity"].to_numpy()
        works["unit_rate"] = quantities["unit_rate"].to_numpy()
        works["expected_log_amount"] = cost.predicted_log_amount.to_numpy()
        works["cost_residual"] = cost.residual.to_numpy()
        works["cost_residual_z"] = cost.residual_z.to_numpy()
        works["expected_cost_signal"] = cost.cost_signal.to_numpy()
        metrics["expected_cost_model"] = cost.metrics

    with timer.stage("state-relative cost"):
        from ml import cost_peers

        peers_path = resolve(cfg["paths"]["models_dir"]) / "cost_peers.joblib"
        if not train_models and peers_path.exists():
            # Scoring run: look the peer statistics up; never derive them from
            # the uploaded batch.
            import joblib

            peer_artifact = joblib.load(peers_path)
        else:
            peer_artifact = cost_peers.fit(works, cfg)
            models["cost_peers"] = peer_artifact

        state_cost = cost_peers.apply(works, peer_artifact, cfg)
        for column in state_cost.columns:
            works[column] = state_cost[column].to_numpy()

        amount = pd.to_numeric(works["sanction_amount"], errors="coerce").astype("float64")
        expected_amount = np.expm1(works["expected_log_amount"].astype("float64"))
        works["expected_cost_amount"] = expected_amount.round(0).to_numpy()
        expected_ratio = (amount / pd.Series(expected_amount).replace(0, np.nan)).round(3)

        combined = cost_peers.combine(works["expected_cost_signal"], state_cost, expected_ratio)
        if bool(cfg["cost_state"].get("drive_cost_signal", False)):
            for column in combined.columns:
                works[column] = combined[column].to_numpy()
        else:
            # Descriptive only: the state comparison is kept for reviewers and
            # the peer-comparison chart, but the score stays on the validated
            # expected-cost channel. See configs/ml.yaml cost_state for why.
            expected = works["expected_cost_signal"].astype("float64")
            works["cost_signal"] = expected.to_numpy()
            works["cost_channel"] = np.where(expected > 0, "expected", "")
            works["cost_ratio"] = expected_ratio.to_numpy()
        works["state_channel_would_fire"] = (combined["cost_channel"] == "state_peer").to_numpy()

        metrics["cost_state_channel"] = {
            "works_with_state_signal": int((works["state_cost_signal"] > 0).sum()),
            "works_with_expected_signal": int((works["expected_cost_signal"] > 0).sum()),
            "works_with_any_cost_signal": int((works["cost_signal"] > 0).sum()),
            "drives_cost_signal": bool(cfg["cost_state"].get("drive_cost_signal", False)),
            "works_where_state_channel_would_lead": int(works["state_channel_would_fire"].sum()),
            "channel_that_fired": {
                str(k): int(v) for k, v in works["cost_channel"].value_counts().items() if str(k)
            },
            "peer_scope_used": {
                str(k): int(v) for k, v in works["state_peer_scope"].value_counts().items()
            },
            "source": "saved training artifact" if not train_models else "fitted on this run",
        }

    with timer.stage("rule layer"):
        from ml.rules import agreement_with_shipped, compute_rules

        rules = compute_rules(works, cfg)
        for col in rules.columns:
            works[col] = rules[col].to_numpy()

        from ml.rules import severe_rules_fired

        severe = severe_rules_fired(works, rules, cfg)
        for col in severe.columns:
            works[col] = severe[col].to_numpy()
        works["severe_rule_count"] = (
            severe.sum(axis=1).astype("int16").to_numpy() if not severe.empty else 0
        )
        metrics["severe_rules"] = {
            **{col: int(severe[col].sum()) for col in severe.columns},
            "works_with_any": int((works["severe_rule_count"] > 0).sum()),
            "works_with_two_or_more": int((works["severe_rule_count"] >= 2).sum()),
        }
        metrics["rule_layer"] = {
            "positive_rate": float(works["rule_label"].mean()),
            "agreement_with_shipped_flags": agreement_with_shipped(works, rules, cfg),
            "note": (
                "Rules are recomputed from observable columns so they respond to "
                "corrected or uploaded data, which the shipped flag_* columns "
                "cannot. They are a fusion signal, never a model input."
            ),
        }

    with timer.stage("features"):
        feats, names = build_features(works, cfg)
        if save:
            save_feature_list(names, cfg)
        metrics["n_features"] = len(names)

    with timer.stage("unsupervised anomaly"):
        anomaly = detect(feats, names, cfg)

    with timer.stage("duplicates"):
        if embeddings is not None:
            dup = find_duplicates(works, embeddings, cfg)
        else:
            from ml.detect_duplicates import DuplicateResult

            dup = DuplicateResult(
                pairs=pd.DataFrame(),
                clusters=pd.DataFrame(),
                dup_score=pd.Series(0.0, index=works.index),
            )
        metrics["duplicates"] = {
            "pairs": int(len(dup.pairs)),
            "clusters": int(len(dup.clusters)),
            "works_flagged": int((dup.dup_score > 0).sum()),
        }

    with timer.stage("split works"):
        split_peers_path = resolve(cfg["paths"]["models_dir"]) / "split_peers.joblib"
        score_with_context = bool(
            cfg["duplicates"]["split_works"].get("score_with_corpus_context", True)
        )
        if not train_models and score_with_context and split_peers_path.exists():
            # Scoring run. Judge the batch against saved national peer medians,
            # and look for groups across the batch AND the existing works in the
            # same districts, so that a split lying partly in an upload, or
            # wholly inside a small one, is still recognised.
            import joblib

            split_stats = joblib.load(split_peers_path)
            context, batch_ids = _with_corpus_context(works, cfg)
            splits = find_split_works(context, cfg, peer_stats=split_stats)
            if not splits.empty:
                touches = splits["work_ids"].map(
                    lambda ids: bool(set(str(ids).split(",")) & batch_ids)
                )
                splits = splits.loc[touches].reset_index(drop=True)
            split_source = (
                f"saved peer stats, {len(context) - len(works):,} corpus works as context"
            )
        else:
            peered = build_peer_groups(works, cfg)
            splits = find_split_works(peered, cfg)
            if train_models:
                from ml.detect_duplicates import fit_split_peer_stats

                models["split_peers"] = fit_split_peer_stats(peered, cfg)
            split_source = "fitted on this run"
        in_split = split_membership(works, splits)
        metrics["split_works"] = {
            "groups": int(len(splits)),
            "works": int((in_split > 0).sum()),
            "with_same_vendor": int(splits["same_vendor"].sum()) if not splits.empty else 0,
            "peer_source": split_source,
        }

    delay_risk = pd.Series(0.0, index=works.index, name="delay_risk")
    delay_reasons = pd.Series([[] for _ in range(len(works))], index=works.index, dtype="object")
    supervised_prob = pd.Series(0.0, index=works.index, name="supervised_prob")
    supervised_reasons = pd.Series(
        [[] for _ in range(len(works))], index=works.index, dtype="object"
    )

    if train_models:
        with timer.stage("delay model"):
            from ml.train_delay import train as train_delay

            delay = train_delay(works, cfg)
            delay_risk = delay.predictions
            delay_reasons = delay.reasons
            metrics["delay_model"] = delay.metrics
            models["delay"] = delay.model

        with timer.stage("supervised proxy model"):
            from ml.train_supervised import train as train_supervised

            sup = train_supervised(works, feats, names, cfg)
            supervised_prob = sup.predictions
            supervised_reasons = sup.reasons
            metrics["supervised_model"] = sup.metrics
            models["supervised"] = sup.model

    with timer.stage("risk fusion"):
        signals = score(
            works,
            feats,
            anomaly.scores,
            supervised_prob,
            dup.dup_score,
            in_split,
            delay_risk,
            cfg,
        )

    with timer.stage("reasons (EN + HI)"):
        reasons_en, reasons_hi = build_reasons(
            works,
            feats,
            anomaly.reasons,
            dup.pairs,
            splits,
            delay_risk,
            delay_reasons,
            cfg,
        )

    with timer.stage("assemble + roll up"):
        # Drop feature columns that repeat a raw column name (days_to_sanction,
        # duration_days, num_payments). Leaving both in makes scored[name]
        # return a two-column frame, which breaks every downstream group-by.
        extra = feats.drop(
            columns=[c for c in feats.columns if c in works.columns], errors="ignore"
        )
        scored = pd.concat([works, extra, signals, reasons_en, reasons_hi], axis=1)
        scored["in_split_group"] = in_split.to_numpy()
        # Keep each detector's own score alongside the fused one. The fused
        # "duplicate" channel is the maximum of the duplicate and split scores,
        # which is right for scoring a work but useless for judging either
        # detector on its own.
        scored["dup_score"] = dup.dup_score.to_numpy()
        scored["split_score"] = in_split.to_numpy()
        # The raw predicted probability, alongside the fused "delay" signal which
        # is that probability minus the base rate. Reviewers need the plain
        # probability ("68% chance of running past a year"); the excess is only
        # meaningful inside the fusion.
        scored["delay_risk"] = delay_risk.to_numpy()
        # The per-detector attributions are (feature, value) tuples. Parquet
        # cannot infer a type for those, so they are stored as JSON strings,
        # which is also what the backend will hand to the dashboard.
        scored["unsup_reasons"] = _as_json(anomaly.reasons)
        scored["supervised_reasons"] = _as_json(supervised_reasons)
        scored["delay_reasons"] = _as_json(delay_reasons)

        rollups = build_rollups(scored, cfg)
        alerts = build_alerts(scored, dup.clusters, splits, cfg, dup_pairs=dup.pairs)

        from ml.risk import band_cutoffs

        # Cut-offs from the BASE score, before the severe floor, so they match
        # the cut-offs score() actually banded with.
        base_scores = (
            scored["base_risk_score"] if "base_risk_score" in scored else scored["risk_score"]
        )
        cuts = band_cutoffs(base_scores, cfg)
        metrics["band_cutoffs"] = {k: round(float(v), 2) for k, v in cuts.items()}
        if "severe_floor_applied" in scored:
            lifted = scored["severe_floor_applied"].astype(bool)
            base_bands = pd.Series(
                [band_for(v, cfg, cuts) for v in base_scores], index=scored.index
            )
            metrics["severe_floor"] = {
                "works_lifted": int(lifted.sum()),
                "works_changing_band": int((base_bands != scored["band"]).sum()),
                "bands_before_floor": {
                    b: int((base_bands == b).sum()) for b in ("Low", "Medium", "High", "Critical")
                },
            }
        if save and train_models:
            # Persist them: an upload must be banded against the national
            # distribution, not against its own handful of rows.
            cuts_path = resolve(cfg["paths"]["models_dir"]) / "band_cutoffs.json"
            cuts_path.parent.mkdir(parents=True, exist_ok=True)
            cuts_path.write_text(json.dumps(metrics["band_cutoffs"], indent=2), encoding="utf-8")

            # And the data cut-off. Every age feature ("days since sanction",
            # "still at Sanction stage after N days") counts to this date. Taken
            # from an upload instead, "today" is the upload's own latest date:
            # the 13 demo works put it at 2025-12-11 and a two-year-old stalled
            # work read as 519 days old instead of 782.
            from ml.features import cutoff_date

            context_path = resolve(cfg["paths"]["models_dir"]) / "scoring_context.json"
            context_path.write_text(
                json.dumps({"cutoff_date": cutoff_date(works, cfg).date().isoformat()}, indent=2),
                encoding="utf-8",
            )
        metrics["band_method"] = str(cfg["risk"].get("band_method", "absolute"))
        band_counts = scored["band"].value_counts()
        metrics["risk_bands"] = {
            b: int(band_counts.get(b, 0)) for b in ("Low", "Medium", "High", "Critical")
        }
        metrics["alerts"] = {
            "total": int(len(alerts)),
            "by_type": alerts["alert_type"].value_counts().to_dict() if not alerts.empty else {},
        }
        metrics["weights"] = dict(cfg["risk"]["weights"])

    if save:
        with timer.stage("save outputs"):
            _save_outputs(scored, alerts, rollups, dup, splits, models, cfg)

    metrics["timings_seconds"] = {k: round(v, 2) for k, v in timer.timings.items()}
    metrics["total_seconds"] = round(timer.total, 2)

    return PipelineResult(
        scored=scored,
        alerts=alerts,
        rollups=rollups,
        duplicates=dup.clusters,
        splits=splits,
        metrics=metrics,
        feature_names=names,
        timings=timer.timings,
    )


def _as_json(series: pd.Series) -> np.ndarray:
    """Serialise a column of (feature, value) tuple lists to JSON strings."""
    return np.array(
        [json.dumps([[str(f), round(float(v), 4)] for f, v in (row or [])]) for row in series],
        dtype=object,
    )


def _to_parquet(df: pd.DataFrame, path: Path) -> None:
    """Write parquet, stringifying list columns pyarrow cannot infer when empty."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False, engine="pyarrow", compression="snappy")


def _save_outputs(
    scored: pd.DataFrame,
    alerts: pd.DataFrame,
    rollups: dict[str, pd.DataFrame],
    dup: Any,
    splits: pd.DataFrame,
    models: dict[str, Any],
    cfg: dict[str, Any],
) -> None:
    paths = cfg["paths"]
    _to_parquet(scored, resolve(paths["scored_works"]))
    if not alerts.empty:
        _to_parquet(alerts, resolve(paths["alerts"]))
    if not dup.clusters.empty:
        _to_parquet(dup.clusters, resolve(paths["duplicates"]))
    if not dup.pairs.empty and "duplicate_pairs" in paths:
        # The pair-level breakdown (cosine, fuzzy, location, amount) is what a
        # reviewer needs to judge a duplicate side by side; clusters alone lose it.
        _to_parquet(dup.pairs, resolve(paths["duplicate_pairs"]))
    if not splits.empty:
        _to_parquet(splits, resolve(paths["split_groups"]))
    for name, frame in rollups.items():
        _to_parquet(frame, resolve(paths[f"rollup_{name}"]))

    if models:
        import joblib

        models_dir = resolve(paths["models_dir"])
        models_dir.mkdir(parents=True, exist_ok=True)
        for name, model in models.items():
            # The expected-cost entry is a bundle (model, SVD, residual stats),
            # not a bare estimator, so it gets its own filename.
            bundles = {
                "expected_cost": "expected_cost.joblib",
                "cost_peers": "cost_peers.joblib",
                "split_peers": "split_peers.joblib",
            }
            filename = bundles.get(name, f"{name}_model.joblib")
            joblib.dump(model, models_dir / filename)


def score_new_works(df: pd.DataFrame, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
    """Score an uploaded batch of works without retraining.

    Reuses the saved delay and supervised models when they exist, so the backend
    can score a CSV upload. The unsupervised and duplicate layers are computed
    within the uploaded batch, so a batch that is small or narrow will produce
    weaker peer comparisons than the full national run. That limitation is
    reported in the returned frame's ``scoring_scope`` column.
    """
    cfg = cfg or load_config("ml")
    set_seed(int(cfg["seed"]))

    # Count ages to the TRAINING data cut-off, not the upload's latest date.
    context_path = resolve(cfg["paths"]["models_dir"]) / "scoring_context.json"
    if not cfg.get("cutoff_date") and context_path.exists():
        import copy

        cfg = copy.deepcopy(cfg)
        cfg["cutoff_date"] = json.loads(context_path.read_text(encoding="utf-8"))["cutoff_date"]

    data_cfg = load_config("data")
    prepared = clean(df, data_cfg) if "work_type" not in df.columns else df.copy()
    result = run(cfg, df=prepared, use_embeddings=True, train_models=False, save=False)

    scored = result.scored
    models_dir = resolve(cfg["paths"]["models_dir"])
    delay_path = models_dir / "delay_model.joblib"
    supervised_path = models_dir / "supervised_model.joblib"

    if delay_path.exists() or supervised_path.exists():
        import joblib

        # Rebuild features from the SCORED frame, not the input. The run above
        # derived work_type, the rule columns and the cost signal; the input
        # frame has none of them, and build_features refuses without work_type.
        context = scored.reset_index(drop=True)
        feats, names = build_features(context, cfg)
        delay_risk = pd.Series(0.0, index=context.index)
        supervised_prob = pd.Series(0.0, index=context.index)

        if delay_path.exists():
            from ml.train_delay import build_matrix

            matrix, _ = build_matrix(context, cfg)
            model = joblib.load(delay_path)
            model.get_booster().set_param({"device": "cpu"})
            delay_risk = pd.Series(model.predict_proba(matrix)[:, 1], index=context.index).where(
                context["completion_date"].isna(), 0.0
            )

        if supervised_path.exists():
            model = joblib.load(supervised_path)
            model.get_booster().set_param({"device": "cpu"})
            supervised_prob = pd.Series(
                model.predict_proba(feats[names])[:, 1], index=context.index
            )

        cuts_path = models_dir / "band_cutoffs.json"
        training_cuts = (
            json.loads(cuts_path.read_text(encoding="utf-8")) if cuts_path.exists() else None
        )
        signals = score(
            context,
            feats,
            context["unsupervised"],
            supervised_prob,
            context["duplicate"],
            context["in_split_group"],
            delay_risk,
            cfg,
            cuts=training_cuts,
        )
        scored = context
        for col in signals.columns:
            scored[col] = signals[col].to_numpy()
        scored["delay_risk"] = delay_risk.to_numpy()

    scored["scoring_scope"] = (
        "peer comparisons computed within the uploaded batch only"
        if len(prepared) < 1000
        else "peer comparisons computed within the uploaded batch"
    )
    return scored
