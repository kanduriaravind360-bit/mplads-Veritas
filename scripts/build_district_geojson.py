"""Build the simplified India district boundaries used by the Risk Map.

    python scripts/build_district_geojson.py <INDIA_DISTRICTS.geojson>

Source: datta07/INDIAN-SHAPEFILES, INDIA/INDIA_DISTRICTS.geojson (MIT licence),
https://github.com/datta07/INDIAN-SHAPEFILES. 820 districts, 1.77 million points.

The raw file is too heavy for a browser, so each ring is simplified with
Douglas-Peucker (tolerance in degrees) and coordinates are rounded. Each feature
keeps only the district and state names plus a ``STATE|DISTRICT`` join key built
the same way as the backend's (backend.app.geo.map_key, which applies
configs/district_aliases.yaml), so the map joins on exactly what the API returns.

It also reports how many eSAKSHI works fall in a district that matched a
boundary, because an unmatched district silently vanishes from a choropleth.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.geo import district_from_ida, map_key, normalise_district  # noqa: E402

OUT = ROOT / "frontend" / "public" / "geo" / "india_districts.json"
TOLERANCE = 0.012  # degrees, roughly 1.3 km
DECIMALS = 3

# Karnataka names in the source are truncated at the first accented vowel ("B",
# "H", "Kol"), a worse form of the encoding problem below. Repaired by the census
# district code (D_CODE), checked against each polygon's centroid.
_KARNATAKA_BY_CODE = {
    "296": "BAGALKOT",
    "297": "BALLARI",
    "298": "BELAGAVI",
    "301": "CHAMARAJANAGAR",
    "302": "CHIKKABALLAPURA",
    "305": "DAVANAGERE",
    "307": "DHARWAD",
    "309": "HASSAN",
    "310": "HAVERI",
    "313": "KOLAR",
    "317": "RAMANAGARA",
    "325": "YADGIR",
}


# The source file stores accented vowels as ASCII symbols, a legacy font-encoding
# artefact: "Kāngra" is "K>NGRA", "Bīdar" is "B\dar", "Dehradūn" is "DEHRAD@N".
# Decoded before normalising, or none of those districts can be joined.
_SOURCE_SYMBOLS = str.maketrans(
    {">": "A", "|": "I", "\\": "I", "#": "U", "@": "U", "&": " AND ", "_": " "}
)


def source_name(props: dict) -> str:
    if props.get("state") == "KARNATAKA" and str(props.get("D_CODE")) in _KARNATAKA_BY_CODE:
        return _KARNATAKA_BY_CODE[str(props["D_CODE"])]
    return (props.get("district") or "").translate(_SOURCE_SYMBOLS)


def source_key(props: dict) -> str:
    """Same shape as backend.app.geo.map_key: ``STATE|DISTRICT``."""
    return f"{normalise_district(props.get('state'))}|{normalise_district(source_name(props))}"


def _perpendicular(point: list[float], start: list[float], end: list[float]) -> float:
    (x, y), (x1, y1), (x2, y2) = point, start, end
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    return abs(dy * x - dx * y + x2 * y1 - y2 * x1) / (dx * dx + dy * dy) ** 0.5


def douglas_peucker(points: list[list[float]], tolerance: float) -> list[list[float]]:
    """Iterative Douglas-Peucker, so deep rings cannot hit the recursion limit."""
    if len(points) < 4:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        best, index = 0.0, first
        for i in range(first + 1, last):
            distance = _perpendicular(points[i], points[first], points[last])
            if distance > best:
                best, index = distance, i
        if best > tolerance:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return [p for p, k in zip(points, keep, strict=True) if k]


def simplify_ring(ring: list[list[float]]) -> list[list[float]] | None:
    out = douglas_peucker(ring, TOLERANCE)
    rounded: list[list[float]] = []
    for x, y in out:
        point = [round(x, DECIMALS), round(y, DECIMALS)]
        if not rounded or point != rounded[-1]:
            rounded.append(point)
    if len(rounded) < 4:
        return None
    if rounded[0] != rounded[-1]:
        rounded.append(rounded[0])
    return rounded


def main(source: Path) -> None:
    raw = json.loads(source.read_text(encoding="utf-8"))
    features = []
    before = after = skipped = 0
    for feature in raw["features"]:
        geometry = feature.get("geometry")
        if not geometry:
            continue
        polygons = (
            geometry["coordinates"]
            if geometry["type"] == "MultiPolygon"
            else [geometry["coordinates"]]
        )
        simplified = []
        for polygon in polygons:
            rings = []
            for ring in polygon:
                before += len(ring)
                small = simplify_ring(ring)
                if small:
                    after += len(small)
                    rings.append(small)
            if rings:
                simplified.append(rings)
        if not simplified:
            continue
        props = feature["properties"]
        if not props.get("district"):
            skipped += 1
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "district": source_name(props).title(),
                    "state": (props["state"] or "").translate(_SOURCE_SYMBOLS).title(),
                    "key": source_key(props),
                },
                "geometry": {"type": "MultiPolygon", "coordinates": simplified},
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "FeatureCollection",
        "attribution": "District boundaries: datta07/INDIAN-SHAPEFILES (MIT), simplified",
        "features": features,
    }
    OUT.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(
        f"{len(features)} districts ({skipped} unnamed features skipped), points {before:,} -> {after:,}, {OUT.stat().st_size / 1e6:.2f} MB"
    )
    _report_match(features)


def _report_match(features: list[dict]) -> None:
    import pandas as pd

    works = pd.read_parquet(ROOT / "data" / "processed" / "works.parquet", columns=["ida", "state"])
    works["key"] = [
        map_key(state, district_from_ida(ida))
        for state, ida in zip(works["state"], works["ida"], strict=True)
    ]
    known = {f["properties"]["key"] for f in features}
    matched = works["key"].isin(known)
    per_district = works.groupby("key").size()
    unmatched = per_district[~per_district.index.isin(known)].sort_values(ascending=False)
    print(
        f"works in a matched district: {matched.mean():.1%} ({int(matched.sum()):,} of {len(works):,})"
    )
    print(f"districts matched: {int(per_district.index.isin(known).sum())} of {len(per_district)}")
    print("largest unmatched:", unmatched.head(25).to_dict())


if __name__ == "__main__":
    main(Path(sys.argv[1]))
