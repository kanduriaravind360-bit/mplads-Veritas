"""Extract physical quantities and unit rates from work descriptions.

A "Road / Pavement" work can be 100 metres or 2 kilometres, so the work type
alone says little about what a work should cost. Where the description states a
quantity, a unit rate (rupees per metre, per watt, per unit) is a far sharper
comparison than any peer-group statistic.

Coverage is the limitation: only about 12% of descriptions state a quantity in a
form worth trusting. :func:`extract` reports it, and the expected-cost model
treats quantity as one signal among several rather than depending on it.

Patterns are ordered most-specific first, and a description is charged to the
first family that matches, so "9.5 mtr pole with 6 LED 150 W" is measured in
metres rather than being double-counted.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

#: (unit, canonical multiplier to the base unit, compiled pattern).
#: The multiplier converts to a single scale per family so that 2 km and 2000 m
#: land on the same axis.
_PATTERNS: tuple[tuple[str, float, re.Pattern[str]], ...] = (
    ("length_m", 1000.0, re.compile(r"(\d+(?:\.\d+)?)\s*(?:k\.?m\b|kilo\s*met)", re.I)),
    (
        "length_m",
        1.0,
        re.compile(
            r"(\d+(?:\.\d+)?)\s*(?:r\.?mt|rmt|running\s*met|mtr?s?\b|met(?:er|re)s?\b|m\.\b)",
            re.I,
        ),
    ),
    (
        "area_sqm",
        0.092903,
        re.compile(r"(\d+(?:\.\d+)?)\s*(?:sq\.?\s?ft|sqft|square\s*feet)", re.I),
    ),
    ("area_sqm", 1.0, re.compile(r"(\d+(?:\.\d+)?)\s*(?:sq\.?\s?m|sqm|square\s*met)", re.I)),
    ("power_w", 1000.0, re.compile(r"(\d+(?:\.\d+)?)\s*kw\b", re.I)),
    ("power_w", 1.0, re.compile(r"(\d+(?:\.\d+)?)\s*(?:watts?|w)\b", re.I)),
    ("volume_l", 1000.0, re.compile(r"(\d+(?:\.\d+)?)\s*(?:kl\b|kilo\s*lit)", re.I)),
    ("volume_l", 1.0, re.compile(r"(\d+(?:\.\d+)?)\s*(?:ltrs?\b|lit(?:er|re)s?\b)", re.I)),
    ("power_hp", 1.0, re.compile(r"(\d+(?:\.\d+)?)\s*(?:h\.?p\.?)\b", re.I)),
    ("bore_mm", 25.4, re.compile(r"(\d+(?:\.\d+)?)\s*(?:inch(?:es)?|\")", re.I)),
    ("bore_mm", 1.0, re.compile(r"(\d+(?:\.\d+)?)\s*mm\b", re.I)),
    (
        "count",
        1.0,
        re.compile(
            r"(\d+)\s*(?:nos?\.?\b|nag\b|units?\b|poles?\b|lights?\b|sets?\b|pcs\b|pieces?\b)",
            re.I,
        ),
    ),
)

#: A quantity outside these bounds is a misparse (a year, a pincode, a serial
#: number), not a measurement. Keyed by unit family.
_PLAUSIBLE: dict[str, tuple[float, float]] = {
    "length_m": (1.0, 50_000.0),
    "area_sqm": (1.0, 100_000.0),
    "power_w": (1.0, 100_000.0),
    "volume_l": (10.0, 10_000_000.0),
    "power_hp": (0.5, 500.0),
    "bore_mm": (10.0, 2000.0),
    "count": (1.0, 5000.0),
}


def _parse_one(text: str) -> tuple[float, str] | tuple[None, None]:
    """Return the first plausible (quantity, unit) found in a description."""
    for unit, multiplier, pattern in _PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        try:
            value = float(match.group(1)) * multiplier
        except (TypeError, ValueError):
            continue
        low, high = _PLAUSIBLE[unit]
        if low <= value <= high:
            return value, unit
    return None, None


def extract(descriptions: pd.Series) -> pd.DataFrame:
    """Extract ``quantity`` and ``quantity_unit`` per description.

    Returns a frame aligned to ``descriptions`` with NaN where nothing
    plausible was found.
    """
    values: list[float] = []
    units: list[str | None] = []
    for text in descriptions.fillna("").astype(str):
        quantity, unit = _parse_one(text)
        values.append(np.nan if quantity is None else quantity)
        units.append(unit)

    return pd.DataFrame(
        {
            "quantity": pd.Series(values, index=descriptions.index, dtype="float64"),
            "quantity_unit": pd.Series(units, index=descriptions.index, dtype="object"),
        }
    )


def add_unit_rates(
    df: pd.DataFrame, quantities: pd.DataFrame, cfg: dict[str, Any] | None = None
) -> pd.DataFrame:
    """Add ``unit_rate`` and its percentile within work_type x state.

    The percentile is computed only among works sharing the same unit family, so
    rupees-per-metre is never ranked against rupees-per-watt. Works with no
    quantity get NaN, and callers must treat that as "no signal" rather than
    zero.
    """
    out = quantities.copy()
    amount = pd.to_numeric(df["sanction_amount"], errors="coerce").astype("float64")
    out["unit_rate"] = (amount / out["quantity"].replace(0, np.nan)).replace(
        [np.inf, -np.inf], np.nan
    )

    group = (
        df["work_type"].astype(str)
        + " | "
        + df["state"].astype(str)
        + " | "
        + out["quantity_unit"].astype(str)
    )
    out["unit_rate_pct"] = out["unit_rate"].groupby(group).rank(pct=True)
    return out


def coverage(quantities: pd.DataFrame) -> dict[str, Any]:
    """Share of works with a usable quantity, overall and per unit family."""
    total = len(quantities)
    found = int(quantities["quantity"].notna().sum())
    per_unit = quantities["quantity_unit"].value_counts().to_dict()
    return {
        "rows": total,
        "with_quantity": found,
        "coverage_pct": round(found / total * 100, 2) if total else 0.0,
        "by_unit": {str(k): int(v) for k, v in per_unit.items()},
    }
