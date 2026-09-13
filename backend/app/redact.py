"""Presentation mode: stable pseudonyms for people's names in API responses.

The repository is public, and screenshots, the deck and any public deployment
are publications. The data names real MPs and vendors, and for Rajya Sabha
members the "constituency" field holds the member's own name. In presentation
mode every one of those is replaced with a stable pseudonym (the same person
always gets the same one), in structured fields and inside free-text
descriptions, before the response leaves the server.

Descriptions also name private beneficiaries ("handpump in front of the house of
Shri X", "X S/o Y ke ghar ke samne", "road from X ke ghar se Y ke ghar tak") and
carry phone numbers. Presentation mode masks name words found by that context,
and every mobile number; on the full extract that touches about 17% of
descriptions. It over-masks a little ("Sri Ram Temple" becomes "[name] Temple"),
which is the right way to fail.

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


_HONORIFICS = frozenset(
    "shri sri sh shree smt shrimati srimati sushri kumari late mr mrs ms".split()
)
# S/o, D/o, W/o (son, daughter, wife of). C/o is left alone: in this data it
# almost always abbreviates "construction of".
_RELATION = re.compile(r"^[sdw]\s*[\\/.]\s*o\.?$", re.IGNORECASE)
# Words that end a name: Hindi postpositions and the common place/structure words
# that follow a name in these descriptions.
_NAME_STOP = frozenset(
    """ke ki ka k ko se me mein par pe ji ghar makan house home residence resident
    near of in at the and to from for village gram vill ward no road gali marg temple
    mandir school son daughter wife r/o block district po ps teh tehsil""".split()
)
_POSSESSIVE = frozenset({"ke", "ki", "ka", "k"})
_PREMISES = frozenset(
    {
        "ghar",
        "ghr",
        "makan",
        "dukan",
        "darwaje",
        "dwar",
        "house",
        "residence",
        "home",
        "shop",
        "land",
    }
)
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
_GLUED = re.compile(r"([,;])(?=\S)")
_HYPHEN_HONORIFIC = re.compile(r"-(?=(?:sh|shri|smt|sri)\b)", re.IGNORECASE)
_KIN = frozenset({"son", "daughter", "wife", "husband"})
_MASK = "[name]"
_MAX_NAME_WORDS = 3


def _bare(token: str) -> str:
    return token.strip(".,;:()[]{}\"'-").lower()


def _is_name_word(token: str) -> bool:
    bare = _bare(token)
    return bool(bare) and bare.isalpha() and bare not in _NAME_STOP


def mask_private_names(text: str | None) -> str | None:
    """Mask words that name a private person, and phone numbers, in free text.

    Names are recognised by context: after an honorific (Shri, Smt, Late),
    around a relation marker (S/o, D/o, W/o), before "ke ghar" / "ki dukan"
    (in front of X's house or shop) and after "house of".
    """
    if not text:
        return text
    text = _PHONE.sub("[phone]", text)
    # "dukan,shri X" and "Contact-Sh. X": give glued punctuation a space.
    text = _GLUED.sub(r"\1 ", text)
    text = _HYPHEN_HONORIFIC.sub("- ", text)
    tokens = text.split()
    masked = [False] * len(tokens)

    def mask_forward(start: int) -> None:
        taken = 0
        i = start
        while i < len(tokens) and taken < _MAX_NAME_WORDS:
            if _bare(tokens[i]) in _HONORIFICS:
                masked[i] = True
                i += 1
                continue
            if not _is_name_word(tokens[i]):
                break
            masked[i] = True
            taken += 1
            if tokens[i][-1:] in ",;:)":
                break
            i += 1

    def mask_backward(end: int, limit: int = _MAX_NAME_WORDS) -> None:
        back = end
        taken = 0
        while back >= 0 and taken < limit and _is_name_word(tokens[back]):
            # A comma right before the marker closes the name; an earlier one ends it.
            if taken and tokens[back][-1:] in ",;:":
                break
            masked[back] = True
            taken += 1
            back -= 1

    for i, token in enumerate(tokens):
        bare = _bare(token)
        following = _bare(tokens[i + 1]) if i + 1 < len(tokens) else ""
        previous = _bare(tokens[i - 1]) if i else ""
        if bare in _HONORIFICS:
            masked[i] = True
            mask_forward(i + 1)
        elif _RELATION.match(token.strip(",;:()")):
            mask_backward(i - 1)
            mask_forward(i + 1)
        elif bare in _POSSESSIVE and following in _PREMISES:
            # "Dharmendra ji ke ghar": step over the respectful "ji".
            start = i - 2 if previous == "ji" else i - 1
            mask_backward(start, limit=2)
        elif bare in _KIN and following == "of":
            mask_forward(i + 2)
        elif bare == "of" and previous in _PREMISES:
            mask_forward(i + 1)

    out: list[str] = []
    for token, hide in zip(tokens, masked, strict=True):
        if not hide:
            out.append(token)
        elif not out or out[-1] != _MASK:
            out.append(_MASK)
    return " ".join(out)


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
            out[key] = mask_private_names(scrub_text(out[key], replacements))
    return out


def scrub_text(text: str, replacements: dict[str, str]) -> str:
    """Replace known names inside free text, longest first."""
    for original in sorted(replacements, key=len, reverse=True):
        if len(original) >= 4:
            text = re.sub(re.escape(original), replacements[original], text, flags=re.IGNORECASE)
    return text


def redact_many(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [redact_record(r) for r in records]
