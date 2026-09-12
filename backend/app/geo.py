"""District names from eSAKSHI implementing-agency strings.

An IDA looks like ``DHARWAD(DEPUTY COMMISSIONER DHARWAR_IDA)`` or
``LUCKNOW(DISTRICT MAGISTRAE LUCKNOW_IDA)``. The district is the part before the
bracket. It is normalised (upper case, single spaces, common spelling variants)
so it can be matched against district boundary names on the map.
"""

from __future__ import annotations

import re

_SPACES = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^A-Z0-9 ]")


def district_from_ida(ida: str | None) -> str:
    if not ida:
        return ""
    head = str(ida).split("(", 1)[0]
    return normalise_district(head)


def normalise_district(name: str | None) -> str:
    if not name:
        return ""
    text = _NON_ALNUM.sub(" ", str(name).upper())
    return _SPACES.sub(" ", text).strip()


def mp_code_from_work_id(work_id: str | None) -> str | None:
    """``WS/MP147/2024-2025/12345`` -> ``147``."""
    if not work_id:
        return None
    match = re.search(r"/MP(\d+)/", str(work_id))
    return match.group(1) if match else None
