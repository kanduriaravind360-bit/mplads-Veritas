"""Row-level scoping: a district user must never read another district.

Each test tries a different door: list filters, detail by id, exports, group
entities, aggregates, cases, reports, writes and uploads. The district under
attack is always KANPUR or PATNA; the attacker is the LUCKNOW reviewer.
"""

from __future__ import annotations

import csv
import io

from tests.api.conftest import KANPUR, LUCKNOW, PATNA


def _ids(response) -> set[str]:  # type: ignore[no-untyped-def]
    assert response.status_code == 200, response.text
    return {
        item["work_id"] if "work_id" in item else item["alert_id"]
        for item in response.json()["items"]
    }


def test_each_role_lists_only_its_own_works(client, auth) -> None:  # type: ignore[no-untyped-def]
    expected = {
        "ministry": 8,
        "state_up": 5,
        "district_lucknow": 2,
        "district_kanpur": 3,
        "state_bihar": 3,
        "mp_147": 5,
    }
    for who, count in expected.items():
        body = client.get("/api/works", headers=auth(who)).json()
        assert body["total"] == count, f"{who} sees {body['total']} works, expected {count}"


def test_district_cannot_widen_scope_with_filters(client, auth) -> None:  # type: ignore[no-untyped-def]
    headers = auth("district_lucknow")
    for query in (
        "state=Bihar",
        "district=KANPUR",
        f"ida={KANPUR}",
        f"ida={PATNA}",
        "q=PAT",
        "source=training&district=PATNA",
    ):
        body = client.get(f"/api/works?{query}", headers=headers).json()
        assert all(w["ida"] == LUCKNOW for w in body["items"]), query
        assert body["total"] == 0, f"{query} returned {body['total']} rows outside Lucknow"


def test_detail_of_another_districts_work_is_404_not_403(client, auth) -> None:  # type: ignore[no-untyped-def]
    headers = auth("district_lucknow")
    assert client.get("/api/works/T/MP147/LKO/1", headers=headers).status_code == 200
    for other in ("T/MP147/KNP/1", "T/MP900/PAT/1", "T/DOES/NOT/EXIST"):
        response = client.get(f"/api/works/{other}", headers=headers)
        # Same answer for "not yours" and "does not exist": no existence oracle.
        assert response.status_code == 404
        assert client.get(f"/api/works/{other}/peers", headers=headers).status_code == 404


def test_alerts_list_detail_and_audit_are_scoped(client, auth) -> None:  # type: ignore[no-untyped-def]
    headers = auth("district_lucknow")
    assert _ids(client.get("/api/alerts", headers=headers)) == {"T/MP147/LKO/1"}
    for other in ("T/MP147/KNP/1", "SPL-KANPUR01", "DUP-PATNA001"):
        assert client.get(f"/api/alerts/{other}", headers=headers).status_code == 404
        assert client.get(f"/api/alerts/{other}/audit", headers=headers).status_code == 404


def test_writes_on_another_districts_alert_are_404(client, auth) -> None:  # type: ignore[no-untyped-def]
    headers = auth("district_lucknow")
    other = "T/MP147/KNP/1"
    assert (
        client.post(
            f"/api/alerts/{other}/transition", json={"to_status": "Under Review"}, headers=headers
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/alerts/{other}/comments", json={"body": "peek"}, headers=headers
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/alerts/{other}/feedback", json={"verdict": "false_positive"}, headers=headers
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/alerts/{other}/assign", json={"assignee_email": None}, headers=headers
        ).status_code
        == 404
    )
    # The Kanpur alert is untouched.
    kanpur = client.get(f"/api/alerts/{other}", headers=auth("district_kanpur")).json()
    assert kanpur["status"] == "Open"
    assert kanpur["comments"] == []


def test_bulk_actions_check_every_alert_individually(client, auth) -> None:  # type: ignore[no-untyped-def]
    body = client.post(
        "/api/alerts/bulk",
        json={
            "alert_ids": ["T/MP900/PAT/1", "SPL-KANPUR01"],
            "action": "transition",
            "to_status": "Under Review",
        },
        headers=auth("district_lucknow"),
    ).json()
    assert body["done"] == []
    assert {f["alert_id"] for f in body["failed"]} == {"T/MP900/PAT/1", "SPL-KANPUR01"}
    assert all("not found" in f["error"] for f in body["failed"])


def test_exports_contain_only_scoped_rows(client, auth) -> None:  # type: ignore[no-untyped-def]
    headers = auth("district_lucknow")
    for path in (
        "/api/works/export.csv",
        "/api/works/export.csv?state=Bihar",
        "/api/alerts/export.csv",
    ):
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        rows = list(csv.DictReader(io.StringIO(response.text)))
        districts = {r.get("district") for r in rows}
        assert districts <= {"LUCKNOW"}, f"{path} leaked {districts}"


def test_duplicate_pairs_need_both_works_in_scope(client, auth) -> None:  # type: ignore[no-untyped-def]
    lucknow = client.get("/api/duplicates", headers=auth("district_lucknow")).json()
    assert lucknow["total"] == 0, (
        "a pair straddling Lucknow and Kanpur must not reach a Lucknow reviewer"
    )
    state = client.get("/api/duplicates", headers=auth("state_up")).json()
    assert state["total"] == 1
    patna_pair = client.get("/api/duplicates", headers=auth("state_bihar")).json()["items"][0][
        "pair_id"
    ]
    assert (
        client.get(f"/api/duplicates/{patna_pair}", headers=auth("district_lucknow")).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/duplicates/{patna_pair}/decision",
            json={"decision": "not_duplicate"},
            headers=auth("district_lucknow"),
        ).status_code
        == 404
    )


def test_split_groups_are_scoped(client, auth) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/splits", headers=auth("district_lucknow")).json()["total"] == 0
    assert (
        client.get("/api/splits/SPL-KANPUR01", headers=auth("district_lucknow")).status_code == 404
    )
    assert (
        client.get("/api/splits/SPL-KANPUR01", headers=auth("district_kanpur")).status_code == 200
    )


def test_aggregates_only_count_scoped_rows(client, auth) -> None:  # type: ignore[no-untyped-def]
    headers = auth("district_lucknow")
    overview = client.get("/api/overview", headers=headers).json()
    assert overview["kpis"]["works"] == 2
    assert {d["key"] for d in overview["top_districts"]} <= {"LUCKNOW"}
    geo = client.get("/api/geo/districts", headers=headers).json()
    assert {r["district"] for r in geo["rows"]} <= {"LUCKNOW"}
    money = client.get("/api/analytics/money-at-risk?by=state", headers=headers).json()
    assert {r["key"] for r in money["rows"]} <= {"Uttar Pradesh"}
    assert money["total_sanctioned"] == 1_050_000
    delay = client.get("/api/predictions/delay", headers=headers).json()
    assert {w["district"] for w in delay["items"]} <= {"LUCKNOW"}
    network = client.get("/api/network/vendors", headers=headers).json()
    vendor_labels = {n["label"] for n in network["nodes"] if n["type"] == "vendor"}
    assert vendor_labels <= {"Invented Builders Lucknow"}


def test_reports_are_scoped(client, auth) -> None:  # type: ignore[no-untyped-def]
    headers = auth("district_lucknow")
    assert client.get("/api/reports/alerts/T/MP147/LKO/1.pdf", headers=headers).status_code == 200
    assert client.get("/api/reports/alerts/T/MP900/PAT/1.pdf", headers=headers).status_code == 404
    assert (
        client.get("/api/reports/district.pdf?district=PATNA", headers=headers).status_code == 404
    )


def test_cases_cannot_reach_or_reveal_other_districts(client, auth) -> None:  # type: ignore[no-untyped-def]
    # Linking another district's alert fails as not found.
    response = client.post(
        "/api/cases",
        json={"title": "Try to grab Patna", "alert_ids": ["T/MP900/PAT/1"]},
        headers=auth("district_lucknow"),
    )
    assert response.status_code == 404
    # A Kanpur case made by the state user is invisible to Lucknow.
    created = client.post(
        "/api/cases",
        json={"title": "Kanpur split", "kind": "split_group", "alert_ids": ["SPL-KANPUR01"]},
        headers=auth("state_up"),
    )
    assert created.status_code == 201, created.text
    case_id = created.json()["id"]
    assert case_id not in {
        c["id"] for c in client.get("/api/cases", headers=auth("district_lucknow")).json()
    }
    assert client.get(f"/api/cases/{case_id}", headers=auth("district_lucknow")).status_code == 404
    assert client.get(f"/api/cases/{case_id}", headers=auth("district_kanpur")).status_code == 200


def test_mp_sees_own_works_but_cannot_review(client, auth) -> None:  # type: ignore[no-untyped-def]
    headers = auth("mp_147")
    works = client.get("/api/works", headers=headers).json()
    assert {w["work_id"].split("/")[1] for w in works["items"]} == {"MP147"}
    # The split group's works are MP 147's, so the MP sees the group alert.
    assert "SPL-KANPUR01" in _ids(client.get("/api/alerts", headers=headers))
    assert client.get("/api/alerts/DUP-PATNA001", headers=headers).status_code == 404
    assert (
        client.post(
            "/api/alerts/T/MP147/LKO/1/transition",
            json={"to_status": "Under Review"},
            headers=headers,
        ).status_code
        == 403
    )
    assert client.get("/api/cases", headers=headers).status_code == 403


def test_upload_for_another_district_is_rejected(client, auth) -> None:  # type: ignore[no-untyped-def]
    row = (
        "work_id,state,ida,constituency,work_description,recommended_date,sanction_date,sanction_amount,work_status\n"
        f"T/MP900/NEW/1,Bihar,{PATNA},X,Road,2025-01-01,2025-01-10,500000,Sanctioned\n"
    )
    response = client.post(
        "/api/ingest",
        files={"file": ("sneaky.csv", row.encode(), "text/csv")},
        data={"commit": "true"},
        headers=auth("district_lucknow"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["scored"] is None and body["committed"] is None
    assert any("outside your scope" in e["message"] for e in body["errors"])
    assert client.get("/api/works/T/MP900/NEW/1", headers=auth("ministry")).status_code == 404


def test_unauthenticated_requests_are_refused(client) -> None:  # type: ignore[no-untyped-def]
    for path in (
        "/api/works",
        "/api/alerts",
        "/api/overview",
        "/api/works/export.csv",
        "/api/models/metrics",
    ):
        assert client.get(path).status_code == 401
    assert (
        client.get("/api/works", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    )
