"""Check that no committed file names a real MP or vendor.

    python scripts/privacy_scan.py

The repository is public. The raw eSAKSHI workbook is public data and is
committed on purpose, but nothing DERIVED may attach a score, flag or narrative
to a named MP or vendor. This scans every tracked file except the raw workbook
for any real MP or vendor name taken from the processed data: text files
directly, the deck through python-pptx. It reports only where a match is, never
the matched name, so its own output is safe to share.

Screenshots cannot be read as text. They are written by the end-to-end suite,
which refuses to run unless the API reports presentation mode.

Needs ``data/processed/works.parquet``, so run it after ``python -m ml.data``.
Exit code 1 if anything is found.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SKIP_SUFFIXES = {".xlsx", ".png", ".jpg", ".npy", ".parquet", ".ico"}
SKIP_FILES = {"frontend/package-lock.json", "frontend/public/geo/india_districts.json"}
# Names this short, or made of generic words, collide with ordinary text.
MIN_LENGTH = 8
GENERIC = re.compile(
    r"^(not available|na|n/a|none|null|nil|self|departmental|department|gram panchayat|"
    r"nagar (palika|nigam|panchayat)|municipal|pwd|rural works|block|zila parishad|"
    r"executive engineer|district|collector|bdo|panchayat)",
    re.IGNORECASE,
)


def real_names() -> set[str]:
    works = pd.read_parquet(
        ROOT / "data" / "processed" / "works.parquet", columns=["mp_name", "vendor_name"]
    )
    names: set[str] = set()
    for column in ("mp_name", "vendor_name"):
        for value in works[column].dropna().astype(str).unique():
            cleaned = re.sub(r"\s+", " ", value).strip()
            if len(cleaned) >= MIN_LENGTH and not GENERIC.match(cleaned):
                names.add(cleaned.lower())
    return names


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    return [
        ROOT / f
        for f in out
        if Path(f).suffix.lower() not in SKIP_SUFFIXES
        and f not in SKIP_FILES
        and not f.startswith("data/raw/")
    ]


def file_text(path: Path) -> str:
    if path.suffix.lower() == ".pptx":
        from pptx import Presentation

        deck = Presentation(str(path))
        parts = []
        for slide in deck.slides:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    parts.append(shape.text_frame.text)
                if getattr(shape, "has_table", False) and shape.has_table:
                    parts.extend(cell.text for row in shape.table.rows for cell in row.cells)
            if slide.has_notes_slide:
                parts.append(slide.notes_slide.notes_text_frame.text)
        return "\n".join(parts)
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def main() -> int:
    names = real_names()
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")\b",
        re.IGNORECASE,
    )
    files = tracked_files()
    hits: list[str] = []
    for path in files:
        text = file_text(path)
        if not text:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(ROOT).as_posix()}:{number}")
    print(f"scanned {len(files)} tracked files against {len(names):,} real MP and vendor names")
    if hits:
        print(f"{len(hits)} line(s) contain a real name:")
        for hit in hits:
            print("  " + hit)
        return 1
    print("no real MP or vendor name found in any committed file")
    return 0


if __name__ == "__main__":
    sys.exit(main())
