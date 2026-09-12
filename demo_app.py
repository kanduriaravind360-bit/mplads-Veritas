"""MPLADS Sentinel - Streamlit demo.

    streamlit run demo_app.py

A temporary presentation app for the hackathon round. It only READS the
artefacts the pipeline already produced; it never trains anything. Everything is
cached so the app opens in about a second.

The full role-based dashboard comes later. This exists to show the model working.

Honesty rules from CLAUDE.md are load-bearing here, because this is the surface a
judge actually sees:

* Nothing is called fraud. Every figure is a "risk indicator for review", and
  every flagged work carries the evidence behind it.
* Constituency figures are labelled "implementation risk of works recommended in
  this constituency", never a judgement of the Member of Parliament.
* Denominators are shown wherever a rate is shown.
* The weak results are on the page, not buried: the proxy-label caveat and the
  split-work detector at 46% both appear on the Model Performance page.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
PROCESSED = ROOT / "data" / "processed"
MODELS = ROOT / "models"

# Few colours, high contrast, readable from the back of a room.
NAVY = "#12294d"
AMBER = "#d98a00"
RED = "#b3261e"
GREY = "#8a94a6"
BAND_COLOURS = {"Low": GREY, "Medium": NAVY, "High": AMBER, "Critical": RED}
BAND_ORDER = ["Low", "Medium", "High", "Critical"]

st.set_page_config(page_title="MPLADS Sentinel", page_icon="🛡️", layout="wide")


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def inr(amount: float) -> str:
    """Rupees in the Indian convention: crore, lakh, then plain."""
    if amount is None or not pd.notna(amount):
        return "NA"
    amount = float(amount)
    if abs(amount) >= 1e7:
        return f"₹{amount / 1e7:,.2f} cr"
    if abs(amount) >= 1e5:
        return f"₹{amount / 1e5:,.2f} L"
    return f"₹{amount:,.0f}"


def indian_count(value: float) -> str:
    return f"{int(value):,}"


def as_list(value: object) -> list[str]:
    """Coerce a reasons cell to a list of strings.

    Parquet hands these back as numpy arrays, and `array or []` raises
    "truth value of an array is ambiguous", so the usual idiom breaks the page.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    try:
        return [str(item) for item in value]
    except TypeError:
        return []


# ---------------------------------------------------------------------------
# Data loading (cached: the app must open fast and never retrain)
# ---------------------------------------------------------------------------

_SCORED_COLUMNS = [
    "work_id",
    "state",
    "ida",
    "constituency",
    "mp_name",
    "chamber",
    "work_type",
    "work_description",
    "work_status",
    "vendor_name",
    "sanction_date",
    "completion_date",
    "sanction_amount",
    "total_fund_disbursed",
    "risk_score",
    "band",
    "reasons_en",
    "reasons_hi",
    "rule",
    "supervised",
    "unsupervised",
    "cost",
    "duplicate",
    "delay",
    "delay_risk",
    "cost_signal",
    "dup_score",
    "split_score",
    "cost_residual",
    "expected_log_amount",
    "peer_group",
    "days_to_sanction",
    "duration_days",
    "delay_reasons",
]


@st.cache_data(show_spinner=False)
def load_scored() -> pd.DataFrame:
    path = PROCESSED / "scored_works.parquet"
    available = pd.read_parquet(path, columns=None).columns
    cols = [c for c in _SCORED_COLUMNS if c in available]
    return pd.read_parquet(path, columns=cols)


@st.cache_data(show_spinner=False)
def load_table(name: str) -> pd.DataFrame:
    path = PROCESSED / f"{name}.parquet"
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_metrics() -> dict[str, Any]:
    path = MODELS / "metrics.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@st.cache_data(show_spinner=False)
def monthly_sanctions(scored: pd.DataFrame) -> pd.DataFrame:
    frame = scored.dropna(subset=["sanction_date"]).copy()
    frame["month"] = frame["sanction_date"].dt.to_period("M").dt.to_timestamp()
    out = (
        frame.groupby("month")
        .agg(works=("work_id", "size"), amount=("sanction_amount", "sum"))
        .reset_index()
    )
    out["is_march"] = out["month"].dt.month == 3
    return out


@st.cache_data(show_spinner=False)
def peer_cost_reference(scored: pd.DataFrame) -> pd.DataFrame:
    return (
        scored.groupby(["work_type", "state"], observed=True)["sanction_amount"]
        .agg(["median", "count"])
        .reset_index()
    )


def missing_artefacts() -> list[str]:
    needed = [PROCESSED / "scored_works.parquet", MODELS / "metrics.json"]
    return [str(p.relative_to(ROOT)) for p in needed if not p.exists()]


# ---------------------------------------------------------------------------
# Shared components
# ---------------------------------------------------------------------------


def header() -> None:
    left, right = st.columns([3, 2])
    with left:
        st.title("MPLADS Sentinel")
        st.caption(
            "Risk indicators for review across MP Local Area Development Scheme works. "
            "Nothing here is a finding of fraud."
        )
    with right:
        st.markdown(
            f"<div style='text-align:right;padding-top:1.6rem'>"
            f"<span style='background:{NAVY};color:#fff;padding:6px 14px;"
            f"border-radius:14px;font-size:0.95rem'>"
            f"Data: 77,312 real MPLADS works from eSAKSHI (2023–2026)</span></div>",
            unsafe_allow_html=True,
        )


def band_badge(band: str) -> str:
    colour = BAND_COLOURS.get(band, GREY)
    return (
        f"<span style='background:{colour};color:#fff;padding:3px 10px;"
        f"border-radius:10px;font-weight:600'>{band}</span>"
    )


def reasons_block(row: pd.Series) -> None:
    english = as_list(row.get("reasons_en"))
    hindi = as_list(row.get("reasons_hi"))
    left, right = st.columns(2)
    with left:
        st.markdown("**Why this was flagged**")
        for text in english:
            st.markdown(f"- {text}")
    with right:
        st.markdown("**कारण (Hindi)**")
        for text in hindi:
            st.markdown(f"- {text}")


def risk_gauge(score: float) -> go.Figure:
    figure = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=float(score),
            number={"font": {"size": 46, "color": NAVY}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1},
                "bar": {"color": NAVY, "thickness": 0.75},
                "steps": [
                    {"range": [0, 64], "color": "#eef1f5"},
                    {"range": [64, 85], "color": "#fdf0d5"},
                    {"range": [85, 95], "color": "#fadfc5"},
                    {"range": [95, 100], "color": "#f7d2ce"},
                ],
            },
        )
    )
    figure.update_layout(height=230, margin={"l": 10, "r": 10, "t": 10, "b": 10})
    return figure


DETECTOR_LABELS = {
    "rule": "Transparent rules",
    "supervised": "Proxy-label model",
    "unsupervised": "Statistical outlier",
    "cost": "Cost vs expected",
    "duplicate": "Duplicate / split",
    "delay": "Delay risk",
}


def detector_chart(row: pd.Series, weights: dict[str, float]) -> go.Figure:
    names, values = [], []
    for key, label in DETECTOR_LABELS.items():
        if key in row.index:
            names.append(label)
            values.append(float(row[key]) * float(weights.get(key, 0.0)))
    figure = px.bar(
        x=values,
        y=names,
        orientation="h",
        labels={"x": "Weighted contribution", "y": ""},
        color_discrete_sequence=[NAVY],
    )
    figure.update_layout(height=260, margin={"l": 10, "r": 10, "t": 10, "b": 10})
    return figure


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def page_overview(scored: pd.DataFrame, metrics: dict[str, Any]) -> None:
    st.subheader("Overview")

    total = len(scored)
    sanctioned = float(scored["sanction_amount"].sum())
    completed = float(scored["completion_date"].notna().mean())
    flagged = int(scored["band"].isin(["High", "Critical"]).sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Works", indian_count(total))
    c2.metric("Sanctioned", f"₹{sanctioned / 1e7:,.0f} cr")
    c3.metric("Completed", f"{completed:.1%}", help=f"of {indian_count(total)} works")
    c4.metric(
        "High or Critical",
        indian_count(flagged),
        help=f"{flagged / total:.1%} of all works, for review",
    )

    left, right = st.columns(2)
    with left:
        st.markdown("**Works by risk band**")
        counts = scored["band"].value_counts().reindex(BAND_ORDER).fillna(0).reset_index()
        counts.columns = ["band", "works"]
        figure = px.bar(
            counts,
            x="band",
            y="works",
            color="band",
            color_discrete_map=BAND_COLOURS,
            text="works",
        )
        figure.update_layout(showlegend=False, height=330, xaxis_title="", yaxis_title="works")
        figure.update_traces(texttemplate="%{text:,}", textposition="outside")
        st.plotly_chart(figure, use_container_width=True)

    with right:
        st.markdown("**Top 10 states by mean risk score**")
        states = load_table("rollup_state")
        if not states.empty:
            top = (
                states.loc[~states["low_volume"]].head(10)
                if "low_volume" in states
                else states.head(10)
            )
            figure = px.bar(
                top.sort_values("risk_index"),
                x="risk_index",
                y="state",
                orientation="h",
                text="works",
                color_discrete_sequence=[NAVY],
            )
            figure.update_layout(height=330, xaxis_title="mean risk score", yaxis_title="")
            figure.update_traces(texttemplate="%{text:,} works", textposition="outside")
            st.plotly_chart(figure, use_container_width=True)
            st.caption("Bars show each state's work count, so a small state is never ranked blind.")

    st.markdown("**Sanctions per month** — March, the year-end rush, is highlighted")
    monthly = monthly_sanctions(scored)
    figure = go.Figure()
    figure.add_bar(
        x=monthly["month"],
        y=monthly["works"],
        marker_color=[AMBER if m else NAVY for m in monthly["is_march"]],
        name="works sanctioned",
        hovertemplate="%{x|%b %Y}<br>%{y:,} works<extra></extra>",
    )
    figure.update_layout(height=320, xaxis_title="", yaxis_title="works sanctioned")
    st.plotly_chart(figure, use_container_width=True)

    march = monthly.loc[monthly["is_march"], "works"].mean()
    other = monthly.loc[~monthly["is_march"], "works"].mean()
    if pd.notna(march) and pd.notna(other) and other > 0:
        st.caption(
            f"March averages {march:,.0f} works a month against {other:,.0f} in other months, "
            f"a factor of {march / other:.1f}."
        )


def page_risk_explorer(scored: pd.DataFrame, metrics: dict[str, Any]) -> None:
    st.subheader("Risk Explorer")
    st.caption("Filter, sort, then select a row to see the evidence behind its score.")

    f1, f2, f3, f4 = st.columns(4)
    states = f1.multiselect("State", sorted(scored["state"].dropna().unique().tolist()))
    types = f2.multiselect("Work type", sorted(scored["work_type"].dropna().unique().tolist()))
    bands = f3.multiselect("Risk band", BAND_ORDER, default=["Critical", "High"])
    min_amount = f4.number_input("Minimum amount (₹)", min_value=0, value=0, step=100000)

    view = scored
    if states:
        view = view[view["state"].isin(states)]
    if types:
        view = view[view["work_type"].isin(types)]
    if bands:
        view = view[view["band"].isin(bands)]
    if min_amount:
        view = view[view["sanction_amount"] >= min_amount]

    view = view.sort_values("risk_score", ascending=False)
    st.markdown(f"**{len(view):,} works** match, of {len(scored):,} total")

    table = view.head(500)[
        ["work_id", "state", "work_type", "sanction_amount", "risk_score", "band"]
    ].rename(columns={"sanction_amount": "amount"})

    selected = st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        height=380,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "amount": st.column_config.NumberColumn("Amount (₹)", format="%.0f"),
            "risk_score": st.column_config.ProgressColumn(
                "Risk", min_value=0, max_value=100, format="%.1f"
            ),
        },
    )

    rows = selected.selection.rows if hasattr(selected, "selection") else []
    if not rows:
        st.info("Select a row above to open the detail panel.")
        return

    work = view.iloc[rows[0]]
    st.divider()
    st.markdown(f"### {work['work_id']} &nbsp; {band_badge(work['band'])}", unsafe_allow_html=True)
    st.write(work["work_description"])

    meta = st.columns(4)
    meta[0].metric("Amount", inr(work["sanction_amount"]))
    meta[1].metric("Work type", str(work["work_type"]))
    meta[2].metric("State", str(work["state"]))
    meta[3].metric("Status", str(work["work_status"]))

    left, right = st.columns([1, 2])
    with left:
        st.markdown("**Risk score**")
        st.plotly_chart(risk_gauge(work["risk_score"]), use_container_width=True)
    with right:
        st.markdown("**What each detector contributed**")
        weights = metrics.get("weights", {})
        st.plotly_chart(detector_chart(work, weights), use_container_width=True)

    reasons_block(work)

    st.markdown("**Cost against the typical work of this type in this state**")
    reference = peer_cost_reference(scored)
    match = reference[
        (reference["work_type"] == work["work_type"]) & (reference["state"] == work["state"])
    ]
    if match.empty:
        st.caption("No peer group with enough works in this state to compare against.")
        return
    typical = float(match["median"].iloc[0])
    peers = int(match["count"].iloc[0])
    compare = pd.DataFrame(
        {
            "which": ["This work", f"Typical ({peers:,} peers)"],
            "amount": [float(work["sanction_amount"]), typical],
        }
    )
    figure = px.bar(
        compare,
        x="which",
        y="amount",
        text="amount",
        color="which",
        color_discrete_sequence=[RED, GREY],
    )
    figure.update_traces(texttemplate="₹%{text:,.0f}", textposition="outside")
    figure.update_layout(showlegend=False, height=300, xaxis_title="", yaxis_title="₹")
    st.plotly_chart(figure, use_container_width=True)
    if typical > 0:
        st.caption(
            f"This work costs {float(work['sanction_amount']) / typical:.1f}x the median for "
            f"{work['work_type']} in {work['state']}, across {peers:,} comparable works."
        )


def page_top_risks(scored: pd.DataFrame) -> None:
    st.subheader("Top 20 risks for review")
    st.caption(
        "Ranked by risk score. Each is a hypothesis for a reviewer, with its evidence attached."
    )

    top = scored.sort_values("risk_score", ascending=False).head(20)
    for position, (_, work) in enumerate(top.iterrows(), start=1):
        reasons = as_list(work.get("reasons_en")) or ["No single dominant reason."]
        with st.container(border=True):
            head, score = st.columns([5, 1])
            with head:
                st.markdown(
                    f"**{position}. {work['work_id']}** &nbsp; {band_badge(work['band'])}",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"{work['work_type']} · {work['state']} · {inr(work['sanction_amount'])}"
                )
                st.markdown(f"› {reasons[0]}")
            with score:
                st.metric("Risk", f"{work['risk_score']:.0f}")

            with st.expander("The numbers behind it"):
                st.write(work["work_description"])
                detail = {
                    "Transparent rules": work.get("rule"),
                    "Proxy-label model": work.get("supervised"),
                    "Statistical outlier": work.get("unsupervised"),
                    "Cost vs expected": work.get("cost"),
                    "Duplicate / split": work.get("duplicate"),
                    "Delay risk": work.get("delay"),
                }
                st.dataframe(
                    pd.DataFrame(
                        {"signal": list(detail), "value (0-1)": [detail[k] for k in detail]}
                    ),
                    hide_index=True,
                    use_container_width=True,
                )
                for text in reasons[1:]:
                    st.markdown(f"- {text}")


def page_duplicates(scored: pd.DataFrame) -> None:
    st.subheader("Duplicates and split works")
    tab_dup, tab_split = st.tabs(["Duplicate clusters", "Split-work groups"])
    lookup = scored.set_index("work_id")

    with tab_dup:
        clusters = load_table("duplicates")
        if clusters.empty:
            st.info("No duplicate clusters in the current output.")
        else:
            # Show the CREDIBLE duplicates first. Sorting by cluster size leads
            # with 292-work solar-light rollouts, which are one catalogue item
            # installed in 292 different villages, not one work entered twice.
            # The scorer already down-weights those by cluster size; the page has
            # to do the same or the demo argues against itself.
            small = clusters[clusters["n_works"] <= 3]
            bulk = len(clusters) - len(small)
            shown = small.sort_values("total_amount", ascending=False).head(15)
            st.caption(
                f"{len(small):,} tight clusters of two or three works, the ones a reviewer can "
                f"confirm fastest. Sorted by value. A further {bulk:,} larger clusters are bulk "
                "rollouts, one catalogue item installed across many villages; the score already "
                "discounts them by cluster size."
            )
            for _, cluster in shown.iterrows():
                ids = [i for i in str(cluster["work_ids"]).split(",") if i in lookup.index][:2]
                if len(ids) < 2:
                    continue
                with st.container(border=True):
                    st.markdown(
                        f"**{cluster['dup_group_id']}** · {cluster['n_works']} works · "
                        f"{cluster['work_type']} · {cluster['constituency']} · "
                        f"total {inr(cluster['total_amount'])}"
                    )
                    left, right = st.columns(2)
                    for column, work_id in zip((left, right), ids, strict=False):
                        work = lookup.loc[work_id]
                        with column:
                            st.markdown(f"`{work_id}`")
                            st.write(str(work["work_description"])[:240])
                            st.caption(
                                f"{inr(work['sanction_amount'])} · sanctioned "
                                f"{pd.Timestamp(work['sanction_date']).date()}"
                            )

    with tab_split:
        splits = load_table("split_groups")
        if splits.empty:
            st.info("No split-work groups in the current output.")
        else:
            st.caption(
                f"{len(splits):,} groups: several small works to one district, each below the "
                "typical cost, together above it."
            )
            shown = splits.sort_values("split_score", ascending=False).head(12)
            for _, group in shown.iterrows():
                with st.container(border=True):
                    st.markdown(
                        f"**{group['split_group_id']}** · {group['n_works']} works · "
                        f"{group['work_type']} · combined {inr(group['total_amount'])}"
                    )
                    st.caption(
                        f"{group['ida']} · sanctioned within {group['span_days']:.0f} days · "
                        f"typical single work {inr(group['peer_median'])}"
                        + (f" · vendor {group['vendor_name']}" if group.get("same_vendor") else "")
                    )
                    ids = [i for i in str(group["work_ids"]).split(",") if i in lookup.index]
                    if ids:
                        members = lookup.loc[ids].reset_index()
                        st.dataframe(
                            members[["work_id", "sanction_date", "sanction_amount"]].rename(
                                columns={"sanction_amount": "amount"}
                            ),
                            hide_index=True,
                            use_container_width=True,
                        )


def page_delay(scored: pd.DataFrame, metrics: dict[str, Any]) -> None:
    st.subheader("Delay early warning")
    if "delay_risk" not in scored.columns:
        st.warning("Re-run `python -m ml.train` to produce delay predictions.")
        return

    open_works = scored[scored["completion_date"].isna()].copy()
    horizon = metrics.get("delay_model", {}).get("horizon_days", 365)
    threshold = 0.70

    high = open_works[open_works["delay_risk"] >= threshold]
    c1, c2, c3 = st.columns(3)
    c1.metric("Ongoing works", indian_count(len(open_works)))
    c2.metric(
        f"At high risk (≥{threshold:.0%})",
        indian_count(len(high)),
        help=f"of {len(open_works):,} ongoing works",
    )
    c3.metric("Value at risk", inr(float(high["sanction_amount"].sum())))
    st.caption(
        f"Risk of not completing within {horizon} days of sanction. Predicted from information "
        "known at sanction time only, using each district's and vendor's record of earlier works."
    )

    top = open_works.sort_values("delay_risk", ascending=False).head(25)
    table = top[
        ["work_id", "state", "work_type", "sanction_amount", "delay_risk", "risk_score"]
    ].rename(columns={"sanction_amount": "amount", "delay_risk": "delay probability"})
    st.dataframe(
        table,
        hide_index=True,
        use_container_width=True,
        height=420,
        column_config={
            "delay probability": st.column_config.ProgressColumn(
                "Delay probability", min_value=0.0, max_value=1.0, format="%.0f%%"
            ),
            "amount": st.column_config.NumberColumn("Amount (₹)", format="%.0f"),
        },
    )

    st.markdown("**Why the top works are predicted to run late**")
    for _, work in top.head(5).iterrows():
        reasons = [r for r in as_list(work.get("reasons_en")) if "chance of running past" in r]
        line = (
            reasons[0]
            if reasons
            else f"{work['delay_risk']:.0%} chance of running past {horizon} days"
        )
        st.markdown(f"- `{work['work_id']}` ({work['state']}) — {line}")


def page_model_performance(metrics: dict[str, Any]) -> None:
    st.subheader("Model performance")

    delay = metrics.get("delay_model", {})
    supervised = metrics.get("supervised_model", {})
    cost = metrics.get("expected_cost_model", {})

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Delay ROC-AUC", f"{delay.get('roc_auc', 0):.3f}")
    c2.metric("Delay PR-AUC", f"{delay.get('pr_auc', 0):.3f}")
    c3.metric("Risk model PR-AUC", f"{supervised.get('pr_auc_oof', 0):.3f}")
    c4.metric("Cost model error", f"{cost.get('mae_as_cost_ratio', 0):.2f}x")

    st.markdown(
        f"""
- **Delay ROC-AUC {delay.get("roc_auc", 0):.3f}** — given one work that ran late and one that did
  not, the model ranks the late one higher about {delay.get("roc_auc", 0):.0%} of the time.
- **Delay PR-AUC {delay.get("pr_auc", 0):.3f}** — how well it finds late works specifically, against
  a base rate of {delay.get("delay_rate_test", 0):.0%}. Tested on later sanctions than it trained on.
- **Risk model PR-AUC {supervised.get("pr_auc_oof", 0):.3f}** — against a base rate of
  {supervised.get("positive_rate", 0):.1%}. Read the caveat below before quoting this.
- **Cost model error {cost.get("mae_as_cost_ratio", 0):.2f}x** — predicted cost is typically within
  that factor of the real one, so a work priced several times higher stands out.
"""
    )

    st.divider()
    st.markdown("### How each detector performs in its own review queue")
    st.caption(
        "A reviewer opens one queue at a time, so each detector is measured on its own ranked "
        "list. Recall is the share of 150 planted test cases the queue surfaces."
    )

    injection = metrics.get("injection_test", {})
    stream = injection.get("per_stream_recall", {})
    if stream:
        labels = {
            "inflated_cost": "Cost inflation",
            "duplicate": "Duplicates",
            "split_group": "Split works",
            "fast_complete": "Fast completion",
        }
        rows = [
            {
                "Detector": labels.get(key, key),
                "Fired at all": f"{value.get('detector_fired', 0):.1%}",
                "Queue size": f"{value.get('queue_size', 0):,}",
                "Recall @1%": f"{value.get('recall_at_top_1pct', 0):.1%}",
                "Recall @5%": f"{value.get('recall_at_top_5pct', 0):.1%}",
                "Recall @10%": f"{value.get('recall_at_top_10pct', 0):.1%}",
            }
            for key, value in sorted(stream.items())
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    st.divider()
    st.markdown("### What we are not claiming")
    st.warning(
        "**The split-work detector is our weakest at 46% and is the main open item.** "
        "It finds fewer than half of the planted split groups. We are showing this rather "
        "than hiding it."
    )
    st.warning(
        "**The risk model learns a rule set, not fraud.** Its target, `anomaly_label`, is a "
        "hand-written rule (a weighted sum of seven flags), not a verified fraud case. A PR-AUC "
        f"of {supervised.get('pr_auc_oof', 0):.3f} means those rules are almost perfectly "
        "reproducible from observable data. It does not mean we detect fraud at that rate."
    )
    st.info(
        "Every output is a **risk indicator for review**. Constituency figures describe the "
        "implementation risk of works recommended there, which is a statement about delivery by "
        "executing agencies, never about the Member of Parliament."
    )

    with st.expander("Global rank recall (kept for continuity, but misleading)"):
        st.write(injection.get("global_rank_recall_note", ""))
        global_recall = injection.get("global_rank_recall", {})
        if global_recall:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Injection": k,
                            "Recall @1%": f"{v.get('recall_at_top_1pct', 0):.1%}",
                            "Recall @5%": f"{v.get('recall_at_top_5pct', 0):.1%}",
                        }
                        for k, v in sorted(global_recall.items())
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )


DEMO_CSV = ROOT / "demo_data" / "live_demo_works.csv"


@st.cache_data(show_spinner=False)
def load_demo_works() -> pd.DataFrame:
    return pd.read_csv(DEMO_CSV) if DEMO_CSV.exists() else pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_holdout_works() -> pd.DataFrame:
    path = PROCESSED / "holdout_works.parquet"
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


def _score(frame: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """Score a batch through the same path an upload takes, and time it."""
    import time as _time

    from ml.pipeline import score_new_works

    start = _time.perf_counter()
    result = score_new_works(frame)
    return result, _time.perf_counter() - start


def _band_summary(result: pd.DataFrame, elapsed: float) -> None:
    st.success(f"{len(result):,} works scored in {elapsed:.1f} s")
    counts = result["band"].value_counts()
    columns = st.columns(4)
    for column, band in zip(columns, BAND_ORDER, strict=False):
        column.metric(band, indian_count(counts.get(band, 0)))


def _results_table(result: pd.DataFrame) -> None:
    view = result.sort_values("risk_score", ascending=False)
    table = view[["work_id", "work_description", "sanction_amount", "risk_score", "band"]].rename(
        columns={"work_description": "description", "sanction_amount": "amount"}
    )
    st.dataframe(
        table,
        hide_index=True,
        use_container_width=True,
        height=380,
        column_config={
            "amount": st.column_config.NumberColumn("Amount", format="%.0f"),
            "risk_score": st.column_config.ProgressColumn(
                "Risk", min_value=0, max_value=100, format="%.1f"
            ),
        },
    )
    st.markdown("**Reasons**")
    for _, work in view.head(8).iterrows():
        reasons = as_list(work.get("reasons_en"))
        with st.container(border=True):
            st.markdown(
                f"**{work['work_id']}** {band_badge(work['band'])} &nbsp; "
                f"{work['risk_score']:.0f} &nbsp; {inr(work['sanction_amount'])}",
                unsafe_allow_html=True,
            )
            for text in reasons[:4]:
                st.markdown(f"- {text}")


def _expected_bands(expected: str) -> set[str]:
    """Parse "Medium or High (cost)" into {"Medium", "High"}."""
    head = str(expected).split("(")[0]
    return {band for band in BAND_ORDER if band in head}


def _demo_verdict(compare: pd.DataFrame) -> str:
    """Say how many demo works landed where intended, naming the misses.

    Computed from the scores on every run, so it can never describe an older
    version of the model than the one on screen.
    """
    hits = compare.apply(lambda r: r["band"] in _expected_bands(r["expected"]), axis=1)
    misses = compare.loc[~hits]
    text = f"{int(hits.sum())} of {len(compare)} demo works land in the band they were built for."
    if not misses.empty:
        listed = "; ".join(
            f"{row['what_it_is']} scored {row['risk_score']:.0f} ({row['band']}), "
            f"built for {row['expected'].split('(')[0].strip()}"
            for _, row in misses.iterrows()
        )
        text += f" Misses, kept in rather than tuned away: {listed}."
    return text


def page_live_scoring(scored: pd.DataFrame) -> None:
    st.subheader("Live scoring")
    st.caption(
        "Works scored on the spot, through exactly the same code path as any uploaded file. "
        "Nothing is retrained and nothing is special-cased."
    )

    tab_demo, tab_holdout, tab_upload = st.tabs(
        ["Score demo works", "Score 100 never-seen works", "Upload your own CSV"]
    )

    with tab_demo:
        st.markdown(
            f"<span style='background:{AMBER};color:#fff;padding:4px 12px;"
            f"border-radius:12px;font-weight:600'>"
            f"Synthetic demo works — not real records</span>",
            unsafe_allow_html=True,
        )
        st.caption(
            "Thirteen invented works with invented vendors and villages, built to exercise each "
            "detector. The MP name is a placeholder; nothing is attributed to a real person."
        )
        demo = load_demo_works()
        if demo.empty:
            st.warning("demo_data/live_demo_works.csv is missing.")
        elif st.button("Score demo works", type="primary", key="score_demo"):
            result, elapsed = _score(demo.drop(columns=["demo_key", "expected_outcome"]))
            _band_summary(result, elapsed)

            expected = dict(zip(demo["work_id"], demo["expected_outcome"], strict=True))
            keys = dict(zip(demo["work_id"], demo["demo_key"], strict=True))
            compare = result.assign(
                what_it_is=result["work_id"].map(keys),
                expected=result["work_id"].map(expected),
            ).sort_values("risk_score", ascending=False)

            st.markdown("**Expected against actual**")
            st.dataframe(
                compare[["what_it_is", "expected", "risk_score", "band", "sanction_amount"]].rename(
                    columns={"sanction_amount": "amount"}
                ),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "amount": st.column_config.NumberColumn("Amount", format="%.0f"),
                    "risk_score": st.column_config.ProgressColumn(
                        "Risk", min_value=0, max_value=100, format="%.1f"
                    ),
                },
            )
            st.info(_demo_verdict(compare))
            _results_table(result)

    with tab_holdout:
        holdout = load_holdout_works()
        if holdout.empty:
            st.warning("No holdout found. Run `python -m ml.train` to build it.")
        else:
            st.markdown(
                f"<span style='background:{NAVY};color:#fff;padding:4px 12px;"
                f"border-radius:12px;font-weight:600'>Excluded from all training</span>",
                unsafe_allow_html=True,
            )
            st.caption(
                f"{len(holdout):,} real works from {holdout['constituency'].nunique()} whole "
                "constituencies, held out before anything was fitted. No model and no peer "
                "statistic has seen them, or their neighbours."
            )
            if st.button("Score 100 never-seen works", type="primary", key="score_holdout"):
                sample = holdout.sample(n=min(100, len(holdout)), random_state=42)
                result, elapsed = _score(sample.reset_index(drop=True))
                _band_summary(result, elapsed)
                _results_table(result)

    with tab_upload:
        demo = load_demo_works()
        if not demo.empty:
            template = demo.drop(columns=["demo_key", "expected_outcome"]).head(3)
            st.download_button(
                "Download a CSV template",
                template.to_csv(index=False).encode("utf-8"),
                file_name="mplads_upload_template.csv",
                mime="text/csv",
            )

        uploaded = st.file_uploader("Upload a CSV of works", type=["csv"])
        if uploaded is None:
            return

        try:
            frame = pd.read_csv(uploaded)
        except Exception as error:  # noqa: BLE001 - surfaced to the presenter
            st.error(f"Could not read that file as CSV: {error}")
            return

        required = [
            "work_id",
            "state",
            "ida",
            "constituency",
            "work_description",
            "sanction_date",
            "sanction_amount",
            "work_status",
        ]
        missing = [column for column in required if column not in frame.columns]
        if missing:
            st.error("This file is missing required columns: " + ", ".join(missing))
            st.caption("Download the template above to see the expected shape.")
            return
        if frame.empty:
            st.error("That file has no rows.")
            return

        st.success(f"Loaded {len(frame):,} rows from {uploaded.name}")
        try:
            result, elapsed = _score(frame)
        except Exception as error:  # noqa: BLE001 - surfaced to the presenter
            st.error(f"Could not score this file: {error}")
            return

        _band_summary(result, elapsed)
        st.caption(
            "Peer comparisons come from within this batch, so a small or narrow upload gives "
            "weaker cost comparisons than the national run. The cost, delay and risk models "
            "themselves are the saved national ones."
        )
        _results_table(result)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

PAGES = {
    "Overview": "overview",
    "Risk Explorer": "explorer",
    "Top Risks": "top",
    "Duplicates & Split Works": "duplicates",
    "Delay Early Warning": "delay",
    "Model Performance": "performance",
    "Live Scoring": "live",
}


def main() -> None:
    missing = missing_artefacts()
    if missing:
        st.title("MPLADS Sentinel")
        st.error("Missing pipeline output: " + ", ".join(missing))
        st.code("python -m ml.train", language="bash")
        return

    scored = load_scored()
    metrics = load_metrics()

    st.sidebar.title("MPLADS Sentinel")
    st.sidebar.caption("Smart India Hackathon 2026 · PS 26102 · MoSPI")
    choice = st.sidebar.radio("Page", list(PAGES), label_visibility="collapsed")
    st.sidebar.divider()
    st.sidebar.caption(
        f"{len(scored):,} works scored\n\n"
        f"{int(scored['band'].isin(['High', 'Critical']).sum()):,} for review"
    )
    st.sidebar.caption("Risk indicators for review, not findings of fraud.")

    header()
    page = PAGES[choice]
    if page == "overview":
        page_overview(scored, metrics)
    elif page == "explorer":
        page_risk_explorer(scored, metrics)
    elif page == "top":
        page_top_risks(scored)
    elif page == "duplicates":
        page_duplicates(scored)
    elif page == "delay":
        page_delay(scored, metrics)
    elif page == "performance":
        page_model_performance(metrics)
    elif page == "live":
        page_live_scoring(scored)


main()
