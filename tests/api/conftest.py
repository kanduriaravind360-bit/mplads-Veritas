"""A small, fully synthetic database for API tests.

Two states, three districts, two MP codes. Every name is invented. The layout is
chosen so each scoping rule has something to leak if it is wrong:

    Uttar Pradesh / LUCKNOW   MP 147   two works (one Critical, one Low)
    Uttar Pradesh / KANPUR    MP 147   three works (High, High, Low) + a split group
    Bihar         / PATNA     MP 900   three works (Critical, Medium, Low) + a duplicate pair

and a duplicate pair that straddles LUCKNOW and KANPUR, which a Lucknow reviewer
must not see because half of it is outside their district.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest

os.environ.setdefault("SCHEDULER_ENABLED", "0")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from backend.app import db as db_module  # noqa: E402
from backend.app import models  # noqa: E402
from backend.app.security import hash_password  # noqa: E402
from backend.app.settings import get_settings  # noqa: E402

PASSWORD = "test-password"

LUCKNOW = "LUCKNOW(DISTRICT MAGISTRATE LUCKNOW_IDA)"
KANPUR = "KANPUR(DISTRICT MAGISTRATE KANPUR_IDA)"
PATNA = "PATNA(DISTRICT MAGISTRATE PATNA_IDA)"

USERS = {
    "ministry": ("ministry@test", "MINISTRY", {}),
    "state_up": ("state.up@test", "STATE", {"state": "Uttar Pradesh"}),
    "district_lucknow": ("district.lucknow@test", "DISTRICT", {"ida": LUCKNOW}),
    "district_kanpur": ("district.kanpur@test", "DISTRICT", {"ida": KANPUR}),
    "state_bihar": ("state.bihar@test", "STATE", {"state": "Bihar"}),
    "mp_147": ("mp.147@test", "MP", {"mp_code": "147"}),
}


def _work(
    work_id: str,
    state: str,
    ida: str,
    mp: str,
    band: str,
    risk: float,
    amount: float,
    **extra: object,
) -> models.Work:
    district = ida.split("(")[0]
    return models.Work(
        work_id=work_id,
        source="training",
        chamber="LS",
        state=state,
        ida=ida,
        district=district,
        constituency=f"{district} CONSTITUENCY",
        mp_code=mp,
        mp_name=f"Invented Member {mp}",
        vendor_name=extra.pop("vendor_name", f"Invented Builders {district.title()}"),
        work_description=extra.pop(
            "work_description", f"Construction of CC road at {district.title()} ward"
        ),
        work_type=extra.pop("work_type", "CC / Concrete Road"),
        work_status="Physical Inspection",
        recommended_date=date(2025, 1, 5),
        sanction_date=extra.pop("sanction_date", date(2025, 2, 1)),
        completion_date=extra.pop("completion_date", None),
        sanction_amount=amount,
        total_fund_disbursed=amount * 0.5,
        is_open=True,
        risk_score=risk,
        base_risk_score=risk,
        band=band,
        delay_risk=extra.pop("delay_risk", 0.3),
        reasons_en=[f"Invented reason for {work_id}"],
        reasons_hi=[f"काल्पनिक कारण {work_id}"],
        detail={},
        rule_round_amount=bool(extra.pop("rule_round_amount", False)),
        **extra,
    )


def seed(session: Session) -> None:
    works = [
        _work("T/MP147/LKO/1", "Uttar Pradesh", LUCKNOW, "147", "Critical", 97.0, 900_000),
        _work(
            "T/MP147/LKO/2",
            "Uttar Pradesh",
            LUCKNOW,
            "147",
            "Low",
            12.0,
            150_000,
            rule_round_amount=True,
        ),
        _work("T/MP147/KNP/1", "Uttar Pradesh", KANPUR, "147", "High", 88.0, 990_000),
        _work("T/MP147/KNP/2", "Uttar Pradesh", KANPUR, "147", "High", 87.0, 995_000),
        _work("T/MP147/KNP/3", "Uttar Pradesh", KANPUR, "147", "Low", 20.0, 300_000),
        _work("T/MP900/PAT/1", "Bihar", PATNA, "900", "Critical", 96.0, 1_200_000),
        _work("T/MP900/PAT/2", "Bihar", PATNA, "900", "Medium", 70.0, 1_190_000),
        _work("T/MP900/PAT/3", "Bihar", PATNA, "900", "Low", 15.0, 200_000),
    ]
    session.add_all(works)
    session.flush()

    raised = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)

    def alert(
        alert_id: str,
        kind: str,
        severity: str,
        work_ids: list[str],
        ida: str,
        state: str,
        amount: float,
    ) -> None:
        session.add(
            models.Alert(
                alert_id=alert_id,
                alert_type=kind,
                severity=severity,
                risk_score=90.0,
                amount=amount,
                n_works=len(work_ids),
                state=state,
                ida=ida,
                district=ida.split("(")[0],
                constituency=f"{ida.split('(')[0]} CONSTITUENCY",
                mp_code=work_ids[0].split("/")[1].removeprefix("MP"),
                work_type="CC / Concrete Road",
                reasons_en=[f"Invented alert reason {alert_id}"],
                reasons_hi=["काल्पनिक"],
                evidence={"work_ids": work_ids},
                raised_at=raised,
                updated_at=raised,
            )
        )
        session.flush()
        for work_id in work_ids:
            session.add(models.AlertWork(alert_id=alert_id, work_id=work_id))

    alert(
        "T/MP147/LKO/1",
        "high_risk_work",
        "Critical",
        ["T/MP147/LKO/1"],
        LUCKNOW,
        "Uttar Pradesh",
        900_000,
    )
    alert(
        "T/MP147/KNP/1",
        "high_risk_work",
        "High",
        ["T/MP147/KNP/1"],
        KANPUR,
        "Uttar Pradesh",
        990_000,
    )
    alert(
        "T/MP900/PAT/1", "high_risk_work", "Critical", ["T/MP900/PAT/1"], PATNA, "Bihar", 1_200_000
    )
    alert(
        "SPL-KANPUR01",
        "split_work_group",
        "High",
        ["T/MP147/KNP/1", "T/MP147/KNP/2"],
        KANPUR,
        "Uttar Pradesh",
        1_985_000,
    )
    alert(
        "DUP-PATNA001",
        "duplicate_group",
        "Medium",
        ["T/MP900/PAT/1", "T/MP900/PAT/2"],
        PATNA,
        "Bihar",
        2_390_000,
    )

    session.add(
        models.SplitGroup(
            split_group_id="SPL-KANPUR01",
            state="Uttar Pradesh",
            ida=KANPUR,
            mp_code="147",
            work_type="CC / Concrete Road",
            vendor_name="Invented Builders Kanpur",
            same_vendor=True,
            n_works=2,
            work_ids=["T/MP147/KNP/1", "T/MP147/KNP/2"],
            total_amount=1_985_000,
            split_score=0.7,
            detail={"span_days": 3},
        )
    )
    pair = {
        "cosine": 0.97,
        "token_set": 95.0,
        "location_overlap": 0.8,
        "amount_similarity": 0.99,
        "days_apart": 4.0,
        "work_type": "CC / Concrete Road",
    }
    session.add(
        models.DuplicatePair(
            work_id_a="T/MP900/PAT/1",
            work_id_b="T/MP900/PAT/2",
            dup_group_id="DUP-PATNA001",
            state="Bihar",
            ida=PATNA,
            mp_code="900",
            pair_score=0.95,
            **pair,
        )
    )
    # Straddles two districts: visible to the UP state user, not to either district user.
    session.add(
        models.DuplicatePair(
            work_id_a="T/MP147/LKO/1",
            work_id_b="T/MP147/KNP/3",
            state="Uttar Pradesh",
            ida=LUCKNOW,
            mp_code="147",
            pair_score=0.91,
            **pair,
        )
    )

    session.add(
        models.MetricDoc(
            key="metrics",
            body={
                "injection_test": {
                    "per_stream_recall": {
                        "split_group": {
                            "detector_fired": 0.46,
                            "recall_at_top_5pct": 0.05,
                            "recall_at_top_10pct": 0.46,
                        }
                    },
                    "weakest_detector_plain_language": "The split-work detector is our weakest at 46% and is the main open item.",
                },
                "delay_model": {"roc_auc": 0.87, "pr_auc": 0.86},
                "supervised_model": {"pr_auc_oof": 0.93, "caveat": "proxy label"},
                "holdout_evaluation": {"n_holdout_works": 10, "n_holdout_constituencies": 2},
            },
        )
    )

    hashed = hash_password(PASSWORD)
    for email, role, scope in USERS.values():
        session.add(models.User(email=email, name=email, role=role, password_hash=hashed, **scope))
    session.commit()


@pytest.fixture(scope="session")
def engine(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    get_settings.cache_clear()
    path = tmp_path_factory.mktemp("api") / "test.db"
    eng = db_module.make_engine(f"sqlite:///{path.as_posix()}")
    db_module.configure(eng)
    db_module.Base.metadata.create_all(eng)
    with db_module.session_factory()() as session:
        seed(session)
    return eng


@pytest.fixture(scope="session")
def client(engine) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    from backend.app.main import app

    with TestClient(app) as test_client:
        yield test_client


_TOKENS: dict[str, str] = {}


@pytest.fixture(scope="session")
def auth(client: TestClient):  # type: ignore[no-untyped-def]
    """``auth("district_lucknow")`` -> Authorization headers for that user."""

    def _headers(who: str) -> dict[str, str]:
        if who not in _TOKENS:
            email = USERS[who][0]
            response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
            assert response.status_code == 200, response.text
            _TOKENS[who] = response.json()["access_token"]
        return {"Authorization": f"Bearer {_TOKENS[who]}"}

    return _headers


@pytest.fixture()
def session(engine) -> Iterator[Session]:  # type: ignore[no-untyped-def]
    with db_module.session_factory()() as s:
        yield s
