"""Happy path for every endpoint, plus the public view's privacy contract."""

from __future__ import annotations

import pytest

MINISTRY_GETS = [
    "/api/health",
    "/api/auth/me",
    "/api/overview",
    "/api/overview/monthly",
    "/api/works",
    "/api/works/facets",
    "/api/works/T/MP900/PAT/2",
    "/api/works/T/MP900/PAT/2/peers",
    "/api/works/export.csv",
    "/api/alerts",
    "/api/alerts/summary",
    "/api/alerts/DUP-PATNA001",
    "/api/alerts/DUP-PATNA001/audit",
    "/api/alerts/export.csv",
    "/api/duplicates",
    "/api/splits",
    "/api/splits/SPL-KANPUR01",
    "/api/network/vendors",
    "/api/network/concentration?min_works=1",
    "/api/network/benford",
    "/api/compliance/rules?min_works=1",
    "/api/compliance/completeness",
    "/api/predictions/delay",
    "/api/predictions/fund-lapse",
    "/api/geo/districts",
    "/api/geo/states",
    "/api/analytics/money-at-risk",
    "/api/analytics/monthly",
    "/api/analytics/category-mix",
    "/api/analytics/cost-distribution",
    "/api/models/metrics",
    "/api/models/summary",
    "/api/cases",
    "/api/cases/suggestions",
    "/api/admin/reviewers",
    "/api/admin/runs",
    "/api/audit/verify",
    "/api/ingest/template.csv",
    "/api/ingest/runs",
    "/api/reports/alerts/DUP-PATNA001.pdf",
    "/api/reports/district.pdf?district=PATNA",
]


@pytest.mark.parametrize("path", MINISTRY_GETS)
def test_get_endpoints_answer(client, auth, path: str) -> None:  # type: ignore[no-untyped-def]
    response = client.get(path, headers=auth("ministry"))
    assert response.status_code == 200, f"{path}: {response.text[:300]}"


def test_pdf_briefs_are_pdfs(client, auth) -> None:  # type: ignore[no-untyped-def]
    response = client.get("/api/reports/alerts/DUP-PATNA001.pdf", headers=auth("ministry"))
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_duplicate_pair_detail_and_decision(client, auth) -> None:  # type: ignore[no-untyped-def]
    headers = auth("state_bihar")
    pair = client.get("/api/duplicates", headers=headers).json()["items"][0]
    detail = client.get(f"/api/duplicates/{pair['pair_id']}", headers=headers).json()
    assert {b["key"] for b in detail["breakdown"]} == {
        "cosine",
        "token_set",
        "location_overlap",
        "amount_similarity",
    }
    assert abs(sum(b["weight"] for b in detail["breakdown"]) - 1.0) < 1e-9
    assert detail["diff"], "a word diff is returned"
    decided = client.post(
        f"/api/duplicates/{pair['pair_id']}/decision",
        json={"decision": "duplicate"},
        headers=headers,
    )
    assert decided.status_code == 200 and decided.json()["decision"] == "duplicate"


def test_case_lifecycle(client, auth) -> None:  # type: ignore[no-untyped-def]
    headers = auth("state_bihar")
    created = client.post(
        "/api/cases",
        json={"title": "Patna duplicate check", "kind": "custom", "alert_ids": ["DUP-PATNA001"]},
        headers=headers,
    )
    assert created.status_code == 201
    case_id = created.json()["id"]
    assert (
        client.post(
            f"/api/cases/{case_id}/notes", json={"body": "called the agency"}, headers=headers
        ).status_code
        == 201
    )
    updated = client.patch(
        f"/api/cases/{case_id}",
        json={"status": "In progress", "add_alert_ids": ["T/MP900/PAT/1"]},
        headers=headers,
    ).json()
    assert updated["status"] == "In progress" and updated["alerts"] == 2
    detail = client.get(f"/api/cases/{case_id}", headers=headers).json()
    assert detail["notes"][0]["body"] == "called the agency"
    assert {e["action"] for e in detail["audit"]} >= {"case_create", "case_note", "case_update"}
    pdf = client.get(f"/api/reports/cases/{case_id}.pdf", headers=headers)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_admin_escalate_is_ministry_only(client, auth) -> None:  # type: ignore[no-untyped-def]
    assert client.post("/api/admin/escalate", headers=auth("state_up")).status_code == 403
    assert client.post("/api/admin/escalate", headers=auth("ministry")).status_code == 200


def test_login_does_not_reveal_which_emails_exist(client) -> None:  # type: ignore[no-untyped-def]
    wrong_password = client.post(
        "/api/auth/login", json={"email": "ministry@test", "password": "nope"}
    )
    unknown_user = client.post("/api/auth/login", json={"email": "nobody@test", "password": "nope"})
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


# --- public citizen view ------------------------------------------------------

_FORBIDDEN_KEYS = {
    "risk_score",
    "band",
    "mp_name",
    "vendor_name",
    "reasons_en",
    "reasons_hi",
    "alert_id",
    "work_id",
}


def _all_keys(value) -> set[str]:  # type: ignore[no-untyped-def]
    if isinstance(value, dict):
        return set(value) | set().union(*(_all_keys(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(_all_keys(v) for v in value)) if value else set()
    return set()


@pytest.mark.parametrize(
    "path", ["/api/public/summary", "/api/public/districts", "/api/public/districts?q=pat"]
)
def test_public_endpoints_need_no_login_and_expose_no_per_work_risk(client, path: str) -> None:  # type: ignore[no-untyped-def]
    response = client.get(path)
    assert response.status_code == 200
    assert not (_all_keys(response.json()) & _FORBIDDEN_KEYS)
    assert "not published per work" in response.json()["note"]


def test_public_district_detail_hides_small_districts(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # The synthetic districts hold 2-3 works, below the publish threshold of 5.
    assert client.get("/api/public/districts/PATNA").status_code == 404
    from backend.app.routers import public

    monkeypatch.setattr(public, "_min_works", lambda: 1)
    body = client.get("/api/public/districts/PATNA").json()
    assert body["works"] == 3
    assert not (_all_keys(body) & _FORBIDDEN_KEYS)


def test_public_districts_are_implementing_agencies(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from backend.app.routers import public

    monkeypatch.setattr(public, "_min_works", lambda: 1)
    rows = client.get("/api/public/districts").json()["districts"]
    patna = next(r for r in rows if r["district"] == "PATNA")
    assert patna["ida"].startswith("PATNA(") and patna["state"] == "Bihar"
    body = client.get("/api/public/districts/PATNA", params={"ida": patna["ida"]}).json()
    assert body["works"] == 3 and body["state"] == "Bihar"


def test_weekly_digest_is_written_to_outbox(engine, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from backend.app import db as db_module
    from backend.app import digest
    from backend.app.scoping import Scope

    monkeypatch.setattr(digest, "OUTBOX", tmp_path)
    with db_module.session_factory()() as session:
        path = digest.write(session, Scope(role="MINISTRY"))
    text = path.read_text(encoding="utf-8")
    assert path.parent == tmp_path and "Nothing here is a finding of fraud" in text
    assert "Invented Member" not in text and "Invented Builders" not in text
