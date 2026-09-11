"""Load, clean and persist the MPLADS works dataset.

Run as::

    python -m ml.data

Reads the ``Data`` sheet of the eSAKSHI extract, parses dates, coerces numeric
types, standardises text and category values, flags date-logic errors (without
dropping the offending rows), and writes ``data/processed/works.parquet``.

LEAKAGE RULE (CLAUDE.md rule 3): ``anomaly_label`` is a proxy label equal to
``anomaly_score >= 4``, where ``anomaly_score`` is a weighted sum of the seven
``flag_*`` columns. Those columns, ``anomaly_score`` and ``flag_reasons`` are
carried through here for auditing only. They must never be used as model input
features.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from ml.config import load_config, resolve

FLAG_COLUMNS: tuple[str, ...] = (
    "flag_sanction_delay",
    "flag_stuck_work",
    "flag_cost_outlier",
    "flag_fast_completion",
    "flag_round_amount",
    "flag_vendor_concentration",
    "flag_payment_stuck",
)

#: Columns that leak the proxy label. Never pass these to a model as features.
LEAKY_COLUMNS: tuple[str, ...] = (*FLAG_COLUMNS, "anomaly_score", "flag_reasons")

DATE_ERROR_COLUMNS: tuple[str, ...] = (
    "date_error_sanction_before_recommendation",
    "date_error_completion_before_sanction",
    "date_error_future_date",
)


def load_raw(cfg: dict[str, Any] | None = None) -> pd.DataFrame:
    """Read the raw ``Data`` sheet from the source workbook, untouched."""
    cfg = cfg or load_config("data")
    path = resolve(cfg["paths"]["raw_xlsx"])
    if not path.exists():
        raise FileNotFoundError(f"source workbook not found: {path}")
    return pd.read_excel(path, sheet_name=cfg["paths"]["sheet"])


def _clean_text(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Trim whitespace and collapse internal runs of whitespace in text columns."""
    for col in columns:
        if col not in df.columns:
            continue
        cleaned = df[col].astype("string").str.strip().str.replace(r"\s+", " ", regex=True)
        df[col] = cleaned.replace("", pd.NA)
    return df


def _standardise_categories(df: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """Map ``work_status`` and ``work_category`` onto canonical spellings."""
    unknown = cfg["missing_category_label"]

    status_map: dict[str, str] = cfg["work_status_map"]
    df["work_status"] = (
        df["work_status"].map(lambda v: status_map.get(v, v)).fillna(unknown).astype("category")
    )

    category_map: dict[str, str] = cfg["work_category_map"]
    df["work_category"] = (
        df["work_category"].map(lambda v: category_map.get(v, v)).fillna(unknown).astype("category")
    )

    for col in ("chamber", "state", "latest_payment_status"):
        df[col] = df[col].astype("category")
    return df


def _parse_dates(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Parse date columns to ``datetime64[ns]``, coercing unparseable values to NaT."""
    for col in columns:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def _coerce_numeric(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Coerce numeric columns to float, leaving counts as nullable integers."""
    integer_like = {"num_payments", "days_to_sanction", "days_since_sanction", "vendor_work_count"}
    for col in columns:
        values = pd.to_numeric(df[col], errors="coerce")
        df[col] = values.astype("Int64") if col in integer_like else values.astype("float64")
    return df


def _snapshot_date(cfg: dict[str, Any]) -> pd.Timestamp:
    """Reference date beyond which a date is treated as a data-entry error."""
    configured = cfg.get("snapshot_date")
    return pd.Timestamp(configured) if configured else pd.Timestamp.today().normalize()


def _add_date_error_flags(df: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """Add boolean date-logic error columns. Offending rows are flagged, not dropped."""
    snapshot = _snapshot_date(cfg)

    df["date_error_sanction_before_recommendation"] = (
        df["sanction_date"] < df["recommended_date"]
    ).fillna(False)
    df["date_error_completion_before_sanction"] = (
        df["completion_date"] < df["sanction_date"]
    ).fillna(False)

    future = pd.Series(False, index=df.index)
    for col in cfg["date_columns"]:
        future |= (df[col] > snapshot).fillna(False)
    df["date_error_future_date"] = future

    df["has_date_error"] = df[list(DATE_ERROR_COLUMNS)].any(axis=1)
    return df


def clean(df: pd.DataFrame, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
    """Return a cleaned copy of the raw works frame.

    Trims text, standardises categories, parses dates, coerces numeric types and
    appends date-logic error flags. No rows are dropped.
    """
    cfg = cfg or load_config("data")
    df = df.copy()

    df = _clean_text(df, list(cfg["text_columns"]))
    df = _standardise_categories(df, cfg)
    df = _parse_dates(df, list(cfg["date_columns"]))
    df = _coerce_numeric(df, list(cfg["numeric_columns"]))

    for col in FLAG_COLUMNS:
        df[col] = df[col].astype(bool)
    df["anomaly_score"] = df["anomaly_score"].astype("int16")
    df["anomaly_label"] = df["anomaly_label"].astype("int8")

    df = _add_date_error_flags(df, cfg)
    return df.sort_values("work_id", kind="stable").reset_index(drop=True)


def compute_anomaly_score(df: pd.DataFrame, cfg: dict[str, Any] | None = None) -> pd.Series:
    """Recompute ``anomaly_score`` from the flag columns and configured weights.

    Used to verify the dataset's own label, never to build model features.
    """
    cfg = cfg or load_config("data")
    weights: dict[str, int] = cfg["flag_weights"]
    score = pd.Series(0, index=df.index, dtype="int16")
    for col, weight in weights.items():
        score += df[col].astype("int16") * weight
    return score


def save_processed(df: pd.DataFrame, cfg: dict[str, Any] | None = None) -> Path:
    """Write the cleaned frame to parquet and return the path."""
    cfg = cfg or load_config("data")
    path = resolve(cfg["paths"]["processed_parquet"])
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False, engine="pyarrow", compression="snappy")
    return path


def load_processed(cfg: dict[str, Any] | None = None) -> pd.DataFrame:
    """Read the cleaned parquet, building it first if it is missing."""
    cfg = cfg or load_config("data")
    path = resolve(cfg["paths"]["processed_parquet"])
    if not path.exists():
        df = clean(load_raw(cfg), cfg)
        save_processed(df, cfg)
        return df
    return pd.read_parquet(path, engine="pyarrow")


def sanity_check(df: pd.DataFrame) -> str:
    """Return the five-line sanity summary printed by ``python -m ml.data``."""
    rows = len(df)
    start = df["recommended_date"].min().date()
    end = df["sanction_date"].max().date()
    label_rate = df["anomaly_label"].mean() * 100
    flagged = int(df["anomaly_label"].sum())
    missing_vendor = df["vendor_name"].isna().mean() * 100
    date_errors = int(df["has_date_error"].sum())

    return "\n".join(
        [
            f"rows                : {rows:,}",
            f"date range          : {start} -> {end} (recommended -> sanction)",
            f"proxy label rate    : {label_rate:.2f}%  ({flagged:,} works)",
            f"missing vendor_name : {missing_vendor:.1f}%",
            f"date-logic errors   : {date_errors:,} works",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    """Build ``data/processed/works.parquet`` and print the sanity check."""
    parser = argparse.ArgumentParser(description="Build the cleaned MPLADS works table.")
    parser.add_argument("--config", default="data", help="config name under configs/")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    df = clean(load_raw(cfg), cfg)
    path = save_processed(df, cfg)

    print(sanity_check(df))
    size_mb = path.stat().st_size / 1e6
    print(f"\nwrote {path.relative_to(resolve('.'))}  ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
