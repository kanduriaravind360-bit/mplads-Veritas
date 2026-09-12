"""District names from eSAKSHI implementing-agency strings.

An IDA looks like ``DHARWAD(DEPUTY COMMISSIONER DHARWAR_IDA)`` or
``LUCKNOW(DISTRICT MAGISTRAE LUCKNOW_IDA)``. The district is the part before the
bracket. It is normalised (upper case, single spaces, common spelling variants)
so it can be matched against district boundary names on the map.
"""

from __future__ import annotations

import re
import unicodedata
from functools import cache

from ml.config import load_config

_SPACES = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^A-Z0-9 ]")


def district_from_ida(ida: str | None) -> str:
    if not ida:
        return ""
    head = str(ida).split("(", 1)[0]
    return normalise_district(head)


def normalise_district(name: str | None) -> str:
    """Upper case, accents transliterated, punctuation to spaces, single spaces.

    Boundary files spell districts with diacritics ("Kāngra", "Bīdar"); without
    transliteration each accented letter became a space and "KANGRA" failed to
    match "K NGRA".
    """
    if not name:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(name))
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    text = _NON_ALNUM.sub(" ", ascii_text.upper())
    return _SPACES.sub(" ", text).strip()


@cache
def _aliases() -> dict[str, dict[str, str]]:
    table = load_config("district_aliases").get("districts") or {}
    return {
        normalise_district(state): {
            normalise_district(k): normalise_district(v) for k, v in (names or {}).items()
        }
        for state, names in table.items()
    }


def map_key(state: str | None, district: str | None) -> str:
    """``STATE|DISTRICT`` in the boundary file's spelling, the Risk Map join key.

    Qualified by state because district names repeat across states.
    """
    state_key = normalise_district(state)
    district_key = normalise_district(district)
    district_key = _aliases().get(state_key, {}).get(district_key, district_key)
    return f"{state_key}|{district_key}"


def mp_code_from_work_id(work_id: str | None) -> str | None:
    """``WS/MP147/2024-2025/12345`` -> ``147``."""
    if not work_id:
        return None
    match = re.search(r"/MP(\d+)/", str(work_id))
    return match.group(1) if match else None
