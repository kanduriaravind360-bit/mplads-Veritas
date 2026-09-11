"""Risk fusion, banding, bilingual reasons and roll-ups.

Blends five signals into one 0-100 ``risk_score``. The weights and their
rationale live in ``configs/ml.yaml``; the reason wording lives in
``configs/reasons.yaml``.

Honesty rules (CLAUDE.md rule 4) are structural here, not cosmetic:

* Every score carries the evidence that produced it. A number with no reason is
  not shown.
* Delay risk applies only to open works. For a completed work its weight is
  removed and the remaining weights are renormalised, so a finished work is not
  quietly credited with a low delay score it never earned.
* The MP roll-up is named ``implementation_risk_index`` and described as the
  implementation risk of works recommended in a constituency. It is a statement
  about delivery by executing agencies, never about the MP.
* Every roll-up carries its denominator, so a 3-work district cannot be ranked
  against a 3,000-work one without the reader seeing why.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ml.config import load_config
from ml.detect_anomaly import FEATURE_FAMILY

_SIGNALS: tuple[str, ...] = ("rule", "supervised", "unsupervised", "duplicate", "delay")


def _as_float(value: Any, default: float = 0.0) -> float:
    """Coerce anything (including pandas NA and None) to a plain float."""
    if value is None or value is pd.NA:
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return default if not np.isfinite(out) else out


def format_inr(amount: float) -> str:
    """Format rupees the way Indian reports do: lakh and crore."""
    if not np.isfinite(amount):
        return "NA"
    if amount >= 1e7:
        return f"Rs {amount / 1e7:.2f} crore"
    if amount >= 1e5:
        return f"Rs {amount / 1e5:.2f} lakh"
    return f"Rs {amount:,.0f}"


def band_for(score: float, cfg: dict[str, Any]) -> str:
    """Map a 0-100 score to its band."""
    bands = cfg["risk"]["bands"]
    if score >= float(bands["critical"]):
        return "Critical"
    if score >= float(bands["high"]):
        return "High"
    if score >= float(bands["medium"]):
        return "Medium"
    return "Low"


def fuse(signals: pd.DataFrame, is_open: pd.Series, cfg: dict[str, Any] | None = None) -> pd.Series:
    """Weighted blend of the five signals, rescaled to 0-100.

    ``signals`` holds one 0-1 column per entry in ``_SIGNALS``. For closed works
    the delay weight is dropped and the rest renormalised, so every work is
    scored on the same 0-100 scale regardless of how many signals apply to it.
    """
    cfg = cfg or load_config("ml")
    weights = cfg["risk"]["weights"]
    method = str(cfg["risk"].get("method", "noisy_or"))
    max_weight = max(float(w) for w in weights.values())

    if method == "soft_or":
        # k is chosen so a single signal at full strength scores
        # single_signal_target. Smooth, monotone, and never saturating, so the
        # ranking stays meaningful all the way to the top of the queue.
        target = float(cfg["risk"]["single_signal_target"])
        k = -np.log(1.0 - target) / max_weight

        evidence = pd.Series(0.0, index=signals.index)
        for name in _SIGNALS:
            weight = float(weights[name])
            values = signals[name].astype("float64").clip(0.0, 1.0).fillna(0.0)
            applies = is_open.to_numpy() if name == "delay" else np.ones(len(signals), dtype=bool)
            evidence += np.where(applies, values * weight, 0.0)
        return (100.0 * (1.0 - np.exp(-k * evidence))).clip(0, 100)

    if method == "noisy_or":
        survival = pd.Series(1.0, index=signals.index)
        for name in _SIGNALS:
            reliability = float(weights[name]) / max_weight
            values = signals[name].astype("float64").clip(0.0, 1.0).fillna(0.0)
            applies = is_open.to_numpy() if name == "delay" else np.ones(len(signals), dtype=bool)
            survival *= np.where(applies, 1.0 - reliability * values, 1.0)
        return (100.0 * (1.0 - survival)).clip(0, 100)

    contribution = pd.Series(0.0, index=signals.index)
    total = pd.Series(0.0, index=signals.index)
    for name in _SIGNALS:
        weight = float(weights[name])
        values = signals[name].astype("float64").clip(0.0, 1.0).fillna(0.0)
        applies = is_open.to_numpy() if name == "delay" else np.ones(len(signals), dtype=bool)
        contribution += np.where(applies, values * weight, 0.0)
        total += np.where(applies, weight, 0.0)
    return (100.0 * contribution / total.replace(0, np.nan)).fillna(0.0).clip(0, 100)


def _rule_signal(df: pd.DataFrame, cfg: dict[str, Any]) -> pd.Series:
    """The transparent rule score, normalised to 0-1.

    Uses the rules recomputed by :mod:`ml.rules` rather than the shipped
    ``anomaly_score``, because the shipped column cannot respond to corrected or
    uploaded data. Normalisation is by the maximum achievable score, not by the
    observed maximum, so the signal means the same thing across runs.

    This is a fusion signal, never a model input (CLAUDE.md rule 3).
    """
    column = "rule_score" if "rule_score" in df.columns else "anomaly_score"
    score = pd.to_numeric(df[column], errors="coerce").astype("float64")

    # Normalise by the LABEL THRESHOLD, not by the maximum achievable score.
    # The threshold is the dataset's own definition of "this work is anomalous",
    # so a work that reaches it should express full rule confidence. Dividing by
    # the maximum (15) instead makes a genuine cost-outlier hit, worth 3 points,
    # read as 0.2 confidence, which buries it. Only a work tripping five rules at
    # once would look serious, and nothing does that.
    threshold = float(cfg["rules"]["label_threshold"])
    return (score / threshold).fillna(0.0).clip(0.0, 1.0)


def _split_signal(in_split: pd.Series) -> pd.Series:
    return in_split.astype("float64")


def _delay_signal(delay_risk: pd.Series, is_open: pd.Series, cfg: dict[str, Any]) -> pd.Series:
    """Delay risk expressed as excess over the observed base rate.

    A predicted 42% chance of running late is unremarkable when 42% of works do
    run late. Only the part above the base rate is evidence of a problem. Using
    the raw probability instead puts a delay floor under half the population and
    inflates the High/Critical queue to a fifth of all works.
    """
    risk = delay_risk.astype("float64").clip(0.0, 1.0).fillna(0.0)
    dcfg = cfg["delay"]

    base = float(dcfg["base_rate_fallback"])
    if bool(dcfg.get("base_rate_from_data", True)):
        open_risk = risk[is_open.to_numpy()]
        if len(open_risk) > 0 and float(open_risk.median()) > 0:
            base = float(open_risk.median())

    return ((risk - base) / max(1e-9, 1.0 - base)).clip(0.0, 1.0)


def _deviation_reason(
    feature: str,
    z: float,
    row: pd.Series,
    peer_stats: dict[str, dict[str, float]],
    templates: dict[str, Any],
) -> tuple[str, str] | None:
    """Render one peer-deviation reason in English and Hindi."""
    family = FEATURE_FAMILY.get(feature)
    block = templates["deviations"].get(family) if family else None
    if block is None:
        return None

    direction = "high" if z > 0 else "low"
    tpl = block[direction]
    stats = peer_stats.get(feature, {})
    median = _as_float(stats.get("median", 0.0))
    value = _as_float(row.get(feature, 0.0))
    ratio = value / median if median else 0.0

    fields = {
        "peer": row.get("peer_label", "its peer group"),
        "value": value,
        "median": median,
        "ratio": ratio,
        "z": z,
        "work_type": row.get("work_type", ""),
        "state": row.get("state", ""),
    }
    try:
        return tpl["en"].format(**fields), tpl["hi"].format(**fields)
    except (KeyError, ValueError):
        return None


def _rule_reasons(row: pd.Series, templates: dict[str, Any]) -> list[tuple[str, str]]:
    """Render the dataset's own flag_reasons text via the template table."""
    # Prefer our recomputed rule text: it reflects the data actually scored.
    raw = str(row.get("rule_reasons") or row.get("flag_reasons") or "")
    if not raw or raw == "No rule-based flags":
        return []

    fields = {
        "amount": format_inr(_as_float(row.get("sanction_amount"))),
        "vendor_works_in_ida": _as_float(row.get("vendor_works_in_ida")),
        "vendor_share": _as_float(row.get("vendor_share_of_ida")),
        "days_to_sanction": _as_float(row.get("days_to_sanction")),
        "duration_days": _as_float(row.get("duration_days")),
        "days_since_sanction": _as_float(row.get("days_since_sanction_open")),
        "work_type": row.get("work_type", ""),
        "work_status": row.get("work_status", ""),
    }
    out: list[tuple[str, str]] = []
    for part in (p.strip() for p in raw.split(";")):
        tpl = templates["rules"].get(part)
        if tpl is None:
            continue
        try:
            out.append((tpl["en"].format(**fields), tpl["hi"].format(**fields)))
        except (KeyError, ValueError):
            out.append((part, part))
    return out


def build_reasons(
    df: pd.DataFrame,
    feats: pd.DataFrame,
    unsup_reasons: pd.Series,
    dup_pairs: pd.DataFrame,
    splits: pd.DataFrame,
    delay_risk: pd.Series,
    delay_reasons: pd.Series,
    cfg: dict[str, Any] | None = None,
) -> tuple[pd.Series, pd.Series]:
    """Merge every detector's evidence into ranked English and Hindi reason lists."""
    cfg = cfg or load_config("ml")
    templates = load_config("reasons")
    max_reasons = int(cfg["risk"]["max_reasons"])
    horizon = int(cfg["delay"]["horizon_days"])
    split_cfg = cfg["duplicates"]["split_works"]

    # Feature values win over the raw columns of the same name: the feature
    # versions are plain floats, whereas the raw ones are nullable integers that
    # surface pandas NA in string formatting.
    feature_cols = feats.drop(columns=["work_id"], errors="ignore")
    context = df.drop(columns=[c for c in feature_cols.columns if c in df.columns])
    context = pd.concat([context, feature_cols], axis=1)
    context["peer_label"] = context["work_type"].astype(str) + " in " + context["state"].astype(str)

    # Peer medians, computed once, for phrasing deviations as multiples.
    peer_stats: dict[str, dict[str, float]] = {}
    for feature in FEATURE_FAMILY:
        if feature in feats.columns:
            peer_stats[feature] = {"median": float(feats[feature].median())}

    dup_partner: dict[str, tuple[str, float, float]] = {}
    if not dup_pairs.empty:
        for a, b, score, days in zip(
            dup_pairs["work_id_a"],
            dup_pairs["work_id_b"],
            dup_pairs["pair_score"],
            dup_pairs["days_apart"],
            strict=True,
        ):
            dup_partner.setdefault(a, (b, float(score), float(days)))
            dup_partner.setdefault(b, (a, float(score), float(days)))

    split_info: dict[str, dict[str, Any]] = {}
    if not splits.empty:
        for _, grp in splits.iterrows():
            for work_id in str(grp["work_ids"]).split(","):
                split_info[work_id] = {
                    "n_works": int(grp["n_works"]),
                    "total_amount": format_inr(float(grp["total_amount"])),
                    "work_type": str(grp["work_type"]),
                }

    en_out: list[list[str]] = []
    hi_out: list[list[str]] = []

    for pos, (_idx, row) in enumerate(context.iterrows()):
        en: list[str] = []
        hi: list[str] = []

        for text_en, text_hi in _rule_reasons(row, templates):
            en.append(text_en)
            hi.append(text_hi)

        work_id = row["work_id"]
        if work_id in dup_partner:
            other, score, days = dup_partner[work_id]
            tpl = templates["duplicates"]["pair"]
            fields = {"other_id": other, "similarity": score, "days_apart": days}
            en.append(tpl["en"].format(**fields))
            hi.append(tpl["hi"].format(**fields))

        if work_id in split_info:
            tpl = templates["split"]["member"]
            fields = {
                **split_info[work_id],
                "window": int(split_cfg["days_window"]),
                "percentile": int(split_cfg["combined_percentile"]),
            }
            en.append(tpl["en"].format(**fields))
            hi.append(tpl["hi"].format(**fields))

        for feature, z in unsup_reasons.iloc[pos] or []:
            rendered = _deviation_reason(feature, z, row, peer_stats, templates)
            if rendered:
                en.append(rendered[0])
                hi.append(rendered[1])

        risk = _as_float(delay_risk.iloc[pos])
        if risk > 0:
            base = templates["delay"]["base"]
            fields = {"probability": risk, "horizon_days": horizon}
            base_en = base["en"].format(**fields)
            base_hi = base["hi"].format(**fields)
            drivers = delay_reasons.iloc[pos] or []
            driver = templates["delay"]["drivers"].get(drivers[0][0]) if drivers else None
            if driver:
                joiner = templates["delay"]["joiner"]
                en.append(joiner["en"].format(base=base_en, driver=driver["en"]))
                hi.append(joiner["hi"].format(base=base_hi, driver=driver["hi"]))
            else:
                en.append(base_en)
                hi.append(base_hi)

        if not en:
            tpl = templates["fallback"]
            en.append(tpl["en"].format(peer=row["peer_label"]))
            hi.append(tpl["hi"].format(peer=row["peer_label"]))

        en_out.append(en[:max_reasons])
        hi_out.append(hi[:max_reasons])

    return (
        pd.Series(en_out, index=df.index, name="reasons_en", dtype="object"),
        pd.Series(hi_out, index=df.index, name="reasons_hi", dtype="object"),
    )


def score(
    df: pd.DataFrame,
    feats: pd.DataFrame,
    anomaly_unsup: pd.Series,
    supervised_prob: pd.Series,
    dup_score: pd.Series,
    in_split: pd.Series,
    delay_risk: pd.Series,
    cfg: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Assemble the signal table, fuse it, and band the result."""
    cfg = cfg or load_config("ml")

    duplicate = pd.concat([dup_score.astype("float64"), _split_signal(in_split)], axis=1).max(
        axis=1
    )
    is_open = df["completion_date"].isna()
    signals = pd.DataFrame(
        {
            "rule": _rule_signal(df, cfg),
            "supervised": supervised_prob.astype("float64"),
            "unsupervised": anomaly_unsup.astype("float64"),
            "duplicate": duplicate,
            "delay": _delay_signal(delay_risk, is_open, cfg),
        },
        index=df.index,
    )
    risk = fuse(signals, is_open, cfg)

    out = signals.copy()
    out["risk_score"] = risk.round(2)
    out["band"] = [band_for(v, cfg) for v in risk]
    return out


def _rollup(scored: pd.DataFrame, key: str, label: str, cfg: dict[str, Any]) -> pd.DataFrame:
    """Aggregate risk for one grouping, always carrying the denominator."""
    alert_bands = set(cfg["risk"]["alert_bands"])
    grp = scored.groupby(key, observed=True)

    out = pd.DataFrame(
        {
            "works": grp.size(),
            "risk_index": grp["risk_score"].mean().round(2),
            "median_risk": grp["risk_score"].median().round(2),
            "high_or_critical": grp["band"].apply(lambda s: int(s.isin(alert_bands).sum())),
            "total_sanctioned": grp["sanction_amount"].sum().round(0),
            "completion_rate": grp["completion_date"]
            .apply(lambda s: float(s.notna().mean()))
            .round(4),
            "median_days_to_sanction": grp["days_to_sanction"].median(),
        }
    ).reset_index()

    out["high_or_critical_pct"] = (out["high_or_critical"] / out["works"] * 100).round(2)

    # A handful of works cannot establish a risk ranking. Flag thin groups and
    # sort them below the rest so the top of any list is always well-evidenced.
    min_works = int(cfg["risk"]["rollup_min_works"])
    out["low_volume"] = out["works"] < min_works
    out = out.rename(columns={key: label})
    return out.sort_values(
        ["low_volume", "risk_index"], ascending=[True, False], kind="stable"
    ).reset_index(drop=True)


def build_rollups(
    scored: pd.DataFrame, cfg: dict[str, Any] | None = None
) -> dict[str, pd.DataFrame]:
    """Roll risk up to state, district (IDA), constituency and vendor."""
    cfg = cfg or load_config("ml")

    rollups = {
        "state": _rollup(scored, "state", "state", cfg),
        "ida": _rollup(scored, "ida", "ida", cfg),
        "vendor": _rollup(
            scored.loc[scored["vendor_name"].notna()], "vendor_name", "vendor_name", cfg
        ),
    }

    mp = _rollup(scored, "constituency", "constituency", cfg)
    names = scored.groupby("constituency", observed=True)["mp_name"].agg(
        lambda s: s.mode().iat[0] if not s.mode().empty else ""
    )
    chambers = scored.groupby("constituency", observed=True)["chamber"].agg(
        lambda s: s.mode().iat[0] if not s.mode().empty else ""
    )
    mp.insert(1, "mp_name", mp["constituency"].map(names))
    mp.insert(2, "chamber", mp["constituency"].map(chambers))
    # CLAUDE.md rule 4: this measures delivery by executing agencies on works
    # recommended in the constituency. It is not a judgement of the MP.
    mp = mp.rename(columns={"risk_index": "implementation_risk_index"})
    mp["measure"] = "implementation risk of works recommended in this constituency"
    rollups["mp"] = mp

    return rollups
