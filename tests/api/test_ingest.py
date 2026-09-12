"""Upload validation, scoring summary, and commit.

Scoring itself is the ML pipeline, covered by tests/test_live_scoring.py; here
it is replaced by a stub so these tests exercise the API contract quickly.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.app.services import ingest as svc
from tests.api.conftest import LUCKNOW

HEADER = "work_id,state,ida,constituency,work_description,recommended_date,sanction_date,sanction_amount,work_status\n"


def _post(client, headers, content: str, commit: bool = False, name: str = "upload.csv"):  # type: ignore[no-untyped-def]
    return client.post(
        "/api/ingest",
        files={"file": (name, content.encode(), "text/csv")},
        data={"commit": str(commit).lower()},
        headers=headers,
    )


@pytest.fixture()
def stub_scoring(monkeypatch):  # type: ignore[no-untyped-def]
    def fake_score(frame: pd.DataFrame):  # type: ignore[no-untyped-def]
        out = frame.copy().reset_index(drop=True)
        out["risk_score"] = [91.0 if i == 0 else 20.0 for i in range(len(out))]
        out["base_risk_score"] = out["risk_score"]
        out["band"] = ["High" if i == 0 else "Low" for i in range(len(out))]
        out["work_type"] = "CC / Concrete Road"
        out["reasons_en"] = [["stub reason"] for _ in range(len(out))]
        out["reasons_hi"] = [["स्टब"] for _ in range(len(out))]
        out["scoring_scope"] = "stub"
        return out, 0.01

    monkeypatch.setattr(svc, "score", fake_score)


def test_template_lists_the_columns(client, auth) -> None:  # type: ignore[no-untyped-def]
    response = client.get("/api/ingest/template.csv", headers=auth("district_lucknow"))
    assert response.status_code == 200
    assert "work_id" in response.text.splitlines()[0]


def test_missing_columns_are_reported(client, auth) -> None:  # type: ignore[no-untyped-def]
    body = _post(client, auth("ministry"), "work_id,state\nX,Bihar\n").json()
    assert body["errors"][0]["message"].startswith("missing required columns")
    assert body["scored"] is None


def test_row_level_errors_carry_row_and_column(client, auth) -> None:  # type: ignore[no-untyped-def]
    content = HEADER + (
        f"N/1,Uttar Pradesh,{LUCKNOW},X,Road,2025-01-01,2025-01-10,-5,Sanctioned\n"
        f"N/2,Uttar Pradesh,{LUCKNOW},X,Road,not-a-date,2025-01-10,1000,Sanctioned\n"
        f"N/2,Uttar Pradesh,{LUCKNOW},X,Road,2025-01-01,2025-01-10,1000,Sanctioned\n"
        f"T/MP147/LKO/1,Uttar Pradesh,{LUCKNOW},X,Road,2025-01-01,2025-01-10,1000,Sanctioned\n"
    )
    errors = _post(client, auth("district_lucknow"), content).json()["errors"]
    found = {(e["row"], e["column"]) for e in errors}
    assert (2, "sanction_amount") in found
    assert (3, "recommended_date") in found
    assert (3, "work_id") in found and (4, "work_id") in found, "duplicate ids within the file"
    assert (5, "work_id") in found, "id already in the system"


def test_non_csv_is_a_clean_422(client, auth) -> None:  # type: ignore[no-untyped-def]
    response = _post(client, auth("ministry"), "hello", name="notes.txt")
    assert response.status_code == 422


@pytest.fixture()
def remove_ingested(session):  # type: ignore[no-untyped-def]
    """Delete committed ingest rows afterwards, so other tests see the seeded data only."""
    yield
    from backend.app import models

    ingested = [
        w for (w,) in session.query(models.Work.work_id).filter(models.Work.source == "ingest")
    ]
    session.query(models.AlertWork).filter(models.AlertWork.work_id.in_(ingested)).delete(
        synchronize_session=False
    )
    session.query(models.Alert).filter(models.Alert.source == "ingest").delete(
        synchronize_session=False
    )
    session.query(models.Work).filter(models.Work.source == "ingest").delete(
        synchronize_session=False
    )
    session.commit()


def test_valid_upload_scores_and_commits(client, auth, stub_scoring, remove_ingested) -> None:  # type: ignore[no-untyped-def]
    content = HEADER + (
        f"UP/NEW/1,Uttar Pradesh,{LUCKNOW},X,New road,2025-03-01,2025-03-05,800000,Sanctioned\n"
        f"UP/NEW/2,Uttar Pradesh,{LUCKNOW},X,New drain,2025-03-01,2025-03-06,200000,Sanctioned\n"
    )
    headers = auth("district_lucknow")
    preview = _post(client, headers, content, commit=False).json()
    assert (
        preview["errors"] == []
        and preview["scored"]["scored"] == 2
        and preview["committed"] is None
    )
    assert client.get("/api/works/UP/NEW/1", headers=headers).status_code == 404, (
        "preview must not write"
    )

    committed = _post(client, headers, content, commit=True).json()
    assert committed["committed"] == {"works": 2, "alerts": 1}
    assert client.get("/api/works/UP/NEW/1", headers=headers).json()["source"] == "ingest"
    assert client.get("/api/alerts/UP/NEW/1", headers=headers).status_code == 200
    runs = client.get("/api/ingest/runs", headers=headers).json()
    assert runs and runs[0]["committed"] is True
