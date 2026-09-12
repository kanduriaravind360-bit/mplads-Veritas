"""Presentation mode: stable pseudonyms for people's names in API responses.

The repository is public, and screenshots, the deck and any public deployment
are publications. The data names real MPs and vendors, and for Rajya Sabha
members the "constituency" field holds the member's own name. In presentation
mode every one of those is replaced with a stable pseudonym (the same person
always gets the same one), in structured fields and inside free-text
descriptions, before the response leaves the server.

Places, work ids, amounts and scores are left as they are: they are what a
reviewer needs, and they do not name a person.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from typing import Any

from backend.app.settings import get_settings

_PERSON_FIELDS = ("mp_name", "vendor_name")
# Rajya Sabha rows carry the member's name, e.g. "Shri X (2022-28) (2022-2028)",
# in the constituency field.
_PERSON_LIKE = re.compile(r"^(shri|smt|dr|km|sushri|prof)\b|\(\d{4}-\d{2,4}\)", re.IGNORECASE)


def _token(kind: str, value: str) -> str:
    digest = hashlib.sha256(f"{kind}:{value.strip().lower()}".encode()).hexdigest()
    return str(int(digest[:8], 16) % 10000).zfill(4)


def pseudonym(kind: str, value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return value
    prefix = get_settings().api["presentation"]
    if kind == "mp":
        return f"{prefix['mp_prefix']}-{_token('mp', str(value))}"
    return f"{prefix['vendor_prefix']} V-{_token('vendor', str(value))}"


def constituency_label(value: str | None) -> str | None:
    """Pseudonymise a constituency only when it is really a person's name."""
    if value and _PERSON_LIKE.search(str(value)):
        return f"Rajya Sabha member {pseudonym('mp', value)}"
    return value


def enabled() -> bool:
    return get_settings().presentation_mode


def redact_record(record: dict[str, Any], names: Iterable[str] = ()) -> dict[str, Any]:
    """Return a copy of ``record`` with people's names replaced, if enabled."""
    if not enabled():
        return record
    out = dict(record)
    replacements: dict[str, str] = {}
    if out.get("mp_name"):
        replacements[str(out["mp_name"])] = str(pseudonym("mp", out["mp_name"]))
        out["mp_name"] = pseudonym("mp", out["mp_name"])
    if out.get("vendor_name"):
        replacements[str(out["vendor_name"])] = str(pseudonym("vendor", out["vendor_name"]))
        out["vendor_name"] = pseudonym("vendor", out["vendor_name"])
    if "constituency" in out:
        original = out["constituency"]
        out["constituency"] = constituency_label(original)
        if original and out["constituency"] != original:
            replacements[str(original)] = str(out["constituency"])
    for name in names:
        if name:
            replacements.setdefault(name, str(pseudonym("vendor", name)))
    for key in ("work_description", "example_description", "title", "summary"):
        if isinstance(out.get(key), str):
            out[key] = scrub_text(out[key], replacements)
    return out


def scrub_text(text: str, replacements: dict[str, str]) -> str:
    """Replace known names inside free text, longest first."""
    for original in sorted(replacements, key=len, reverse=True):
        if len(original) >= 4:
            text = re.sub(re.escape(original), replacements[original], text, flags=re.IGNORECASE)
    return text


def redact_many(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [redact_record(r) for r in records]
