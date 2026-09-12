"""District join keys for the Risk Map."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.geo import district_from_ida, map_key, normalise_district

GEO = Path(__file__).resolve().parents[1] / "frontend" / "public" / "geo" / "india_districts.json"


def test_normalise_transliterates_accents() -> None:
    assert normalise_district("Kāngra") == "KANGRA"
    assert normalise_district("  dehradūn  ") == "DEHRADUN"


def test_district_from_ida_takes_the_part_before_the_bracket() -> None:
    assert district_from_ida("DHARWAD(DEPUTY COMMISSIONER DHARWAR_IDA)") == "DHARWAD"


def test_aliases_are_scoped_to_their_state() -> None:
    assert map_key("West Bengal", "HOOGHLY") == "WEST BENGAL|HUGLI"
    # Raigad is Maharashtra's spelling; Chhattisgarh's own Raigarh must be untouched.
    assert map_key("Maharashtra", "RAIGAD") == "MAHARASHTRA|RAIGARH"
    assert map_key("Chhattisgarh", "RAIGARH") == "CHHATTISGARH|RAIGARH"
    assert map_key("Odisha", "RAIGAD") == "ODISHA|RAIGAD"


@pytest.mark.skipif(not GEO.exists(), reason="boundary file not built")
def test_every_alias_target_exists_in_the_boundary_file() -> None:
    from ml.config import load_config

    keys = {f["properties"]["key"] for f in json.loads(GEO.read_text(encoding="utf-8"))["features"]}
    table = load_config("district_aliases")["districts"]
    missing = [
        f"{state}|{target}"
        for state, names in table.items()
        for target in names.values()
        if map_key(state, target) not in keys
    ]
    assert not missing, missing
