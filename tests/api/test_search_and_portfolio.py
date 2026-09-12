"""Palette search and MP portfolio stay inside the caller's scope."""

from __future__ import annotations


def test_search_finds_works_in_scope(client, auth) -> None:  # type: ignore[no-untyped-def]
    body = client.get("/api/search", params={"q": "T/MP"}, headers=auth("ministry")).json()
    ids = {w["work_id"] for w in body["works"]}
    assert "T/MP900/PAT/1" in ids and "T/MP147/LKO/1" in ids


def test_search_never_leaks_across_scope(client, auth) -> None:  # type: ignore[no-untyped-def]
    body = client.get("/api/search", params={"q": "T/MP"}, headers=auth("district_lucknow")).json()
    assert body["works"] and all("/LKO/" in w["work_id"] for w in body["works"])
    assert all(a["district"] == "LUCKNOW" for a in body["alerts"])
    districts = client.get("/api/search", params={"q": "PAT"}, headers=auth("state_up")).json()
    assert districts["districts"] == [] and districts["works"] == []


def test_search_requires_two_characters(client, auth) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/search", params={"q": "T"}, headers=auth("ministry")).status_code == 422


def test_mp_sees_only_their_own_portfolio(client, auth) -> None:  # type: ignore[no-untyped-def]
    own = client.get("/api/portfolio", headers=auth("mp_147"))
    assert own.status_code == 200
    body = own.json()
    assert body["mp_code"] == "147" and body["kpis"]["works"] == 5
    assert "not a judgement of the Member" in body["framing"]
    other = client.get("/api/portfolio", params={"mp_code": "900"}, headers=auth("mp_147"))
    assert other.status_code == 404


def test_portfolio_is_narrowed_by_the_caller_scope(client, auth) -> None:  # type: ignore[no-untyped-def]
    # A Lucknow district officer looking at MP 147 sees only the Lucknow works of that MP.
    body = client.get(
        "/api/portfolio", params={"mp_code": "147"}, headers=auth("district_lucknow")
    ).json()
    assert body["kpis"]["works"] == 2
    assert all(w["district"] == "LUCKNOW" for w in body["attention"])
    # And a UP state officer cannot open a Bihar constituency at all.
    assert (
        client.get(
            "/api/portfolio", params={"mp_code": "900"}, headers=auth("state_up")
        ).status_code
        == 404
    )


def test_constituency_list_is_alphabetical_and_unranked(client, auth) -> None:  # type: ignore[no-untyped-def]
    body = client.get("/api/portfolio/constituencies", headers=auth("ministry")).json()
    keys = [(r["state"], r["constituency"]) for r in body["items"]]
    assert keys == sorted(keys)
    assert all("risk" not in k for row in body["items"] for k in row)
