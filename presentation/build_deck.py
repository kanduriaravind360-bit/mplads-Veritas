"""Build the SIH pitch deck: presentation/MPLADS_Sentinel_SIH26102.pptx.

    python presentation/build_deck.py

Every number on a slide is read at build time from ``models/metrics.json`` or the
application database, never typed in, so the deck cannot drift from the system.
Screenshots come from ``presentation/assets/screens`` (written by the end-to-end
suite in presentation mode, so names are pseudonymised). If
``presentation/template.pptx`` exists its slide masters are used.

Speaker notes carry the talk track for each slide.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCREENS = ROOT / "presentation" / "assets" / "screens"
TEMPLATE = ROOT / "presentation" / "template.pptx"
OUT = ROOT / "presentation" / "MPLADS_Sentinel_SIH26102.pptx"

NAVY = RGBColor(0x0B, 0x1F, 0x3A)
NAVY_DEEP = RGBColor(0x06, 0x12, 0x24)
CARD = RGBColor(0x12, 0x2A, 0x4C)
LINE = RGBColor(0x24, 0x3E, 0x63)
SAFFRON = RGBColor(0xC5, 0x5A, 0x11)
SAFFRON_TEXT = RGBColor(0xF0, 0x93, 0x4B)
WHITE = RGBColor(0xE6, 0xED, 0xF7)
MUTED = RGBColor(0x94, 0xA6, 0xBF)
RED = RGBColor(0xEF, 0x44, 0x44)
AMBER = RGBColor(0xEA, 0xB3, 0x08)
GREEN = RGBColor(0x34, 0xC7, 0x78)
BLUE = RGBColor(0x60, 0xA5, 0xFA)

TITLE_FONT = "Segoe UI Semibold"
BODY_FONT = "Segoe UI"
W, H = Inches(13.333), Inches(7.5)


# ---------------------------------------------------------------- numbers


def inr(amount: float) -> str:
    if amount >= 1e9:
        return f"₹{amount / 1e7:,.0f} crore"
    if amount >= 1e7:
        return f"₹{amount / 1e7:,.2f} crore"
    if amount >= 1e5:
        return f"₹{amount / 1e5:,.1f} lakh"
    return f"₹{amount:,.0f}"


def indian(n: float) -> str:
    """77312 -> 77,312; 1234567 -> 12,34,567."""
    s = f"{int(round(n))}"
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail])


def pct(x: float, digits: int = 0) -> str:
    return f"{x * 100:.{digits}f}%"


def gather() -> dict[str, Any]:
    metrics = json.loads((ROOT / "models" / "metrics.json").read_text(encoding="utf-8"))
    from sqlalchemy import func, select

    from backend.app import db as dbm
    from backend.app import models, queries
    from backend.app.scoping import Scope
    from backend.app.services import learning

    dbm.configure(
        dbm.make_engine(f"sqlite:///{(ROOT / 'data' / 'app' / 'sentinel.db').as_posix()}")
    )
    with dbm.session_factory()() as session:
        totals = queries.totals(session, Scope(role="MINISTRY"))
        # The demo district officer's own scope, as the loader resolved it.
        district_user = (
            session.execute(
                select(models.User).where(models.User.role == "DISTRICT").order_by(models.User.id)
            )
            .scalars()
            .first()
        )
        lucknow = (
            queries.totals(session, Scope.for_user(district_user)) if district_user else totals
        )
        learned = learning.learn(session)
        alerts = session.execute(
            select(func.count()).select_from(models.Alert).where(models.Alert.is_active.is_(True))
        ).scalar_one()
    return {
        "m": metrics,
        "totals": totals,
        "lucknow": lucknow,
        "learning": learned,
        "alerts": alerts,
    }


# ---------------------------------------------------------------- drawing


def blank(prs: Presentation) -> Any:
    layout = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[-1]
    slide = prs.slides.add_slide(layout)
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = NAVY_DEEP
    return slide


def box(
    slide: Any,
    x: float,
    y: float,
    w: float,
    h: float,
    color: RGBColor,
    line: RGBColor | None = None,
    radius: bool = True,
) -> Any:
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
        Inches(x),
        Inches(y),
        Inches(w),
        Inches(h),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line
        shape.line.width = Pt(0.75)
    if radius:
        shape.adjustments[0] = 0.06
    shape.shadow.inherit = False
    return shape


def text(
    slide: Any,
    x: float,
    y: float,
    w: float,
    h: float,
    value: str,
    size: int = 16,
    color: RGBColor = WHITE,
    bold: bool = False,
    font: str = BODY_FONT,
    align: PP_ALIGN = PP_ALIGN.LEFT,
    anchor: MSO_ANCHOR = MSO_ANCHOR.TOP,
) -> Any:
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = shape.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = anchor
    frame.margin_left = frame.margin_right = Inches(0.05)
    frame.margin_top = frame.margin_bottom = Inches(0.02)
    for i, line in enumerate(value.split("\n")):
        para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        para.alignment = align
        run = para.add_run()
        run.text = line
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.name = font
        run.font.color.rgb = color
    return shape


def bullets(
    slide: Any,
    x: float,
    y: float,
    w: float,
    h: float,
    items: list[str],
    size: int = 16,
    color: RGBColor = WHITE,
    gap: int = 8,
) -> None:
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = shape.text_frame
    frame.word_wrap = True
    for i, item in enumerate(items):
        para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        para.space_after = Pt(gap)
        marker = para.add_run()
        marker.text = "▸  "
        marker.font.size = Pt(size)
        marker.font.color.rgb = SAFFRON_TEXT
        marker.font.name = BODY_FONT
        run = para.add_run()
        run.text = item
        run.font.size = Pt(size)
        run.font.color.rgb = color
        run.font.name = BODY_FONT


def header(slide: Any, eyebrow: str, title: str) -> None:
    box(slide, 0.6, 0.55, 0.08, 0.72, SAFFRON, radius=False)
    text(slide, 0.85, 0.45, 11.5, 0.35, eyebrow.upper(), size=12, color=SAFFRON_TEXT, bold=True)
    text(slide, 0.85, 0.72, 11.8, 0.8, title, size=30, bold=True, font=TITLE_FONT)


def footer(slide: Any, number: int) -> None:
    text(
        slide,
        0.6,
        7.02,
        8,
        0.3,
        "MPLADS Sentinel  ·  SIH 2026  ·  PS 26102  ·  Risk indicators for review, never findings of fraud",
        size=10,
        color=MUTED,
    )
    text(slide, 12.2, 7.02, 0.6, 0.3, str(number), size=10, color=MUTED, align=PP_ALIGN.RIGHT)


def kpi(
    slide: Any,
    x: float,
    y: float,
    w: float,
    label: str,
    value: str,
    sub: str = "",
    accent: RGBColor = WHITE,
) -> None:
    box(slide, x, y, w, 1.35, CARD, LINE)
    text(slide, x + 0.2, y + 0.14, w - 0.4, 0.3, label.upper(), size=10, color=MUTED, bold=True)
    text(
        slide,
        x + 0.2,
        y + 0.42,
        w - 0.4,
        0.55,
        value,
        size=26,
        color=accent,
        bold=True,
        font=TITLE_FONT,
    )
    if sub:
        text(slide, x + 0.2, y + 0.95, w - 0.4, 0.35, sub, size=11, color=MUTED)


def notes(slide: Any, value: str) -> None:
    slide.notes_slide.notes_text_frame.text = value


_tmp = Path(tempfile.mkdtemp(prefix="deck-"))


def screenshot(
    slide: Any,
    name: str,
    x: float,
    y: float,
    w: float,
    h: float | None = None,
    top_crop: float | None = None,
) -> None:
    """Place a screenshot, cropped to the visible top of a tall full-page shot.

    ``name`` is "role-page" (e.g. "ministry-delays"): the numeric position the
    end-to-end suite puts in the file name changes as pages are added, so it is
    matched loosely.
    """
    role, _, page = name.partition("-")
    matches = sorted(SCREENS.glob(f"{role}-*-{page}.png"))
    source = matches[0] if matches else SCREENS / f"{name}.png"
    if not source.exists():
        box(slide, x, y, w, h or w * 9 / 16, CARD, LINE)
        text(
            slide,
            x,
            y + 0.2,
            w,
            0.4,
            f"[missing screenshot: {name}]",
            size=12,
            color=MUTED,
            align=PP_ALIGN.CENTER,
        )
        return
    image = Image.open(source).convert("RGB")
    ratio = (h / w) if h else (9 / 16)
    if top_crop is not None:
        ratio = top_crop
    crop_h = min(image.height, int(image.width * ratio))
    image = image.crop((0, 0, image.width, crop_h))
    if image.width > 1800:
        image = image.resize((1800, int(image.height * 1800 / image.width)), Image.LANCZOS)
    target = _tmp / f"{name}.jpg"
    image.save(target, "JPEG", quality=86, optimize=True)
    height = Inches(w * image.height / image.width)
    frame = box(slide, x - 0.04, y - 0.04, w + 0.08, Emu(height).inches + 0.08, LINE, radius=False)
    frame.fill.fore_color.rgb = LINE
    slide.shapes.add_picture(str(target), Inches(x), Inches(y), width=Inches(w))


def arrow(slide: Any, x1: float, y1: float, x2: float, y2: float) -> None:
    connector = slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2)
    )
    connector.line.color.rgb = SAFFRON_TEXT
    connector.line.width = Pt(2)
    line = connector.line._get_or_add_ln()
    tail = line.makeelement(
        "{http://schemas.openxmlformats.org/drawingml/2006/main}tailEnd", {"type": "triangle"}
    )
    line.append(tail)


# ---------------------------------------------------------------- slides


def build() -> Path:
    data = gather()
    m, t, learned = data["m"], data["totals"], data["learning"]
    inj = m["injection_test"]["per_stream_recall"]
    holdout = m["holdout_evaluation"]
    delay_holdout = holdout["delay_model"]["holdout"]
    prs = Presentation(str(TEMPLATE)) if TEMPLATE.exists() else Presentation()
    prs.slide_width, prs.slide_height = W, H
    n = 0

    # 1. Title
    n += 1
    s = blank(prs)
    box(s, 0, 0, 13.333, 7.5, NAVY, radius=False)
    box(s, 0.9, 1.6, 0.12, 2.3, SAFFRON, radius=False)
    text(
        s,
        1.2,
        1.45,
        11,
        0.4,
        "SIH 2026  ·  PROBLEM STATEMENT 26102  ·  MINISTRY OF STATISTICS AND PROGRAMME IMPLEMENTATION",
        size=12,
        color=SAFFRON_TEXT,
        bold=True,
    )
    text(s, 1.2, 1.95, 11, 1.2, "MPLADS Sentinel", size=60, bold=True, font=TITLE_FONT)
    text(
        s,
        1.2,
        3.05,
        11,
        1.0,
        "Risk indicators for review of MPLADS works:\nanomalies, fraud risk, delays and duplicate works, with the evidence attached.",
        size=22,
        color=WHITE,
    )
    text(
        s,
        1.2,
        4.7,
        11,
        0.5,
        f"Built on {indian(t['works'])} real works from the public eSAKSHI extract  ·  {indian(t['mps'])} MPs  ·  {indian(t['districts'])} districts",
        size=16,
        color=MUTED,
    )
    text(s, 1.2, 6.3, 6, 0.4, "[Team name and members]", size=14, color=MUTED)
    notes(
        s,
        "Open with the one-line promise: every MPLADS work gets a risk indicator with its evidence, for a human reviewer. Say 'for review' out loud; we never call anything fraud.",
    )

    # 2. Problem
    n += 1
    s = blank(prs)
    header(s, "The problem", "Too many works, too few reviewers, and no single view")
    kpi(
        s, 0.85, 1.75, 2.85, "Works in the extract", indian(t["works"]), "Lok Sabha and Rajya Sabha"
    )
    kpi(
        s,
        3.9,
        1.75,
        2.85,
        "Sanctioned",
        inr(t["sanctioned"]),
        f"{pct(t['utilisation'])} disbursed so far",
    )
    kpi(
        s,
        6.95,
        1.75,
        2.85,
        "Completed",
        pct(t["completion_rate"]),
        f"{indian(t['completed'])} of {indian(t['works'])}",
    )
    kpi(
        s,
        10.0,
        1.75,
        2.5,
        "Districts",
        indian(t["districts"]),
        f"{indian(t['mps'])} MPs recommending",
    )
    bullets(
        s,
        0.85,
        3.55,
        11.8,
        3.2,
        [
            "A district office cannot read tens of thousands of work records looking for the few that need a second look.",
            "The warning signs are scattered: a cost far above what the description predicts, the same asset recorded twice, one project split to stay under a limit, works stalled for years.",
            "Oversight has to respect scope: a district sees its district, an MP sees works recommended in their constituency, citizens see where money went.",
            "Any flag must come with evidence a reviewer can check, in English and Hindi, and every action must leave an audit trail.",
        ],
        size=17,
    )
    footer(s, n)
    notes(
        s,
        "Frame the scale with the four numbers. The point is triage: the system decides where to look first, people decide what it means.",
    )

    # 3. Architecture
    n += 1
    s = blank(prs)
    header(s, "How it works", "From a spreadsheet extract to a scoped review queue")
    stages = [
        ("eSAKSHI extract", f"{indian(t['works'])} works, 34 columns\npublic data"),
        (
            "ML pipeline",
            f"work type ({m['work_type']['n_types']} types)\nexpected cost, rules\nanomaly, duplicates\nsplits, delay model",
        ),
        ("Fusion", "soft-OR of 6 channels\npercentile bands\nsevere-rule floor"),
        ("FastAPI", "JWT, 4 roles\nrow-level scoping\nhash-chained audit"),
        ("Dashboard", "React, English and Hindi\nreview, cases, learning\ncitizen view"),
    ]
    x = 0.85
    for i, (title, body) in enumerate(stages):
        box(s, x, 2.2, 2.2, 2.05, CARD, LINE)
        text(
            s,
            x + 0.15,
            2.35,
            1.9,
            0.45,
            title,
            size=17,
            bold=True,
            color=SAFFRON_TEXT,
            font=TITLE_FONT,
        )
        text(s, x + 0.15, 2.9, 1.95, 1.9, body, size=13, color=WHITE)
        if i < len(stages) - 1:
            arrow(s, x + 2.22, 3.2, x + 2.48, 3.2)
        x += 2.5
    bullets(
        s,
        0.85,
        4.75,
        11.8,
        1.6,
        [
            f"The full pipeline runs in {m['total_seconds']:.0f} seconds on an RTX 5060; uploads are scored by the same saved models.",
            "Thresholds live in YAML config; the proxy label's flags are never model inputs (leakage rule enforced in code).",
        ],
        size=15,
        color=MUTED,
    )
    footer(s, n)
    notes(
        s,
        "Walk left to right. Emphasise that fusion is transparent: six channels, fixed weights from config, percentile bands so the queue size stays workable.",
    )

    # 4. Command Centre
    n += 1
    s = blank(prs)
    header(s, "Command Centre", "Where to look first, with the denominator always shown")
    screenshot(s, "ministry-command-centre", 0.85, 1.7, 8.2, top_crop=9 / 16)
    kpi(
        s,
        9.35,
        1.7,
        3.15,
        "High or Critical works",
        indian(t["high_or_critical"]),
        f"{pct(t['high_or_critical'] / t['works'], 1)} of all works",
        accent=AMBER,
    )
    kpi(
        s,
        9.35,
        3.2,
        3.15,
        "Money at risk",
        inr(t["money_at_risk"]),
        f"{pct(t['money_at_risk_share'], 1)} of sanctioned value",
        accent=RED,
    )
    kpi(
        s, 9.35, 4.7, 3.15, "Open alerts", indian(data["alerts"]), "works, duplicate groups, splits"
    )
    text(
        s,
        9.35,
        6.15,
        3.15,
        0.7,
        "Bands are percentiles: top 1% Critical, next 4% High, so the queue stays a workable size.",
        size=11,
        color=MUTED,
    )
    footer(s, n)
    notes(
        s,
        "Point at money at risk and its share of sanctioned value. The caveat strip on every page says what the numbers are and are not.",
    )

    # 5. Alert triage
    n += 1
    s = blank(prs)
    header(s, "Alerts inbox", "Every flag explained in English and Hindi")
    screenshot(s, "ministry-alert-drawer", 0.85, 1.7, 6.0)
    screenshot(s, "ministry-what-would-clear", 7.05, 1.7, 5.45)
    bullets(
        s,
        0.85,
        5.3,
        11.8,
        1.6,
        [
            "Keyboard triage (j, k, e), an evidence drawer with reasons, detector channels, peer cost comparison and the audit trail.",
            '"What would clear this" names the evidence a score rests on and the check that would resolve it, never what should have been sanctioned.',
        ],
        size=15,
    )
    footer(s, n)
    notes(
        s,
        "The Bhatpara CCTV example: two works flagged as duplicates and over-cost. The drawer shows why, and the reviewer can clear it: different police stations and wards, and the cost model grouped CCTV with computers.",
    )

    # 6. Duplicates and splits
    n += 1
    s = blank(prs)
    split = inj["split_group"]
    header(
        s, "Duplicates and split works", "One asset recorded twice, or one project cut into pieces"
    )
    screenshot(s, "ministry-split-groups", 0.85, 1.7, 7.4)
    kpi(
        s,
        8.55,
        1.7,
        3.95,
        "Duplicate pairs scored",
        indian(m["duplicates"]["pairs"]),
        f"{indian(m['duplicates']['clusters'])} groups, {indian(m['duplicates']['works_flagged'])} works",
    )
    kpi(
        s,
        8.55,
        3.2,
        3.95,
        "Split-work groups",
        indian(m["split_works"]["groups"]),
        f"{indian(m['split_works']['works'])} works, {indian(m['split_works']['with_same_vendor'])} with one vendor",
    )
    box(s, 8.55, 4.75, 3.95, 1.9, RGBColor(0x3A, 0x2A, 0x0A), AMBER)
    text(s, 8.75, 4.85, 3.6, 0.35, "OUR WEAKEST DETECTOR", size=11, color=AMBER, bold=True)
    text(
        s,
        8.75,
        5.15,
        3.6,
        1.45,
        f"The split-work detector flags only {pct(split['detector_fired'])} of planted split groups. It is the main open item, and the dashboard says so wherever splits appear.",
        size=13,
    )
    footer(s, n)
    notes(
        s,
        "Madurai: twelve road works from one agency sanctioned the same day, each just below a round amount. Then say plainly that split detection is the weakest detector.",
    )

    # 7. Delays
    n += 1
    s = blank(prs)
    header(s, "Delays and early warning", "Which open works are likely to run past a year")
    screenshot(s, "ministry-delays", 0.85, 1.7, 7.4)
    kpi(
        s,
        8.55,
        1.7,
        3.95,
        "Holdout ROC-AUC",
        f"{delay_holdout['roc_auc']:.3f}",
        f"PR-AUC {delay_holdout['pr_auc']:.3f} on {indian(delay_holdout['n_labelled'])} labelled works",
    )
    kpi(
        s,
        8.55,
        3.2,
        3.95,
        "Held-out constituencies",
        indian(holdout["n_holdout_constituencies"]),
        f"{indian(holdout['n_holdout_works'])} works removed before any fitting",
    )
    bullets(
        s,
        8.55,
        4.75,
        3.95,
        2.2,
        [
            f"Time-split ROC-AUC {m['delay_model']['roc_auc']:.3f} inside training.",
            "Fund-lapse figures are labelled estimates: the extract has no release ledger.",
        ],
        size=13,
        color=MUTED,
    )
    footer(s, n)
    notes(
        s,
        "The honest check is the holdout: whole constituencies removed before anything was fitted.",
    )

    # 8. Scoping
    n += 1
    s = blank(prs)
    lk = data["lucknow"]
    header(
        s,
        "Four roles, one source of truth",
        "Everyone sees exactly their scope, enforced on every query",
    )
    screenshot(s, "ministry-risk-map", 0.85, 1.7, 5.9)
    screenshot(s, "state-risk-map", 6.95, 1.7, 5.55)
    bullets(
        s,
        0.85,
        5.3,
        11.8,
        1.6,
        [
            f"Ministry: all India. State: its state. District: its office ({indian(lk['works'])} works for Lucknow). MP: implementation risk of works recommended in their constituency, never a judgement of the Member.",
            "An out-of-scope id answers 404, so the API does not even confirm it exists. End-to-end tests log in as each role to prove it.",
        ],
        size=15,
    )
    footer(s, n)
    notes(
        s,
        "Left is the ministry map, right the same page for the Uttar Pradesh officer. Mention the MP framing explicitly.",
    )

    # 9. Learning and simulator
    n += 1
    s = blank(prs)
    header(
        s, "Learning from reviewers", "Verdicts re-weight detectors, measured on held-back labels"
    )
    screenshot(s, "ministry-learning", 0.85, 1.7, 6.0)
    screenshot(s, "ministry-simulator-changed", 7.05, 1.7, 5.45)
    if learned.get("status") == "ok":
        p = learned["precision"]
        line = (
            f"On {indian(p['evaluate_rows'])} held-back labels, precision at {p['k']} is {p['configured_fusion']:.2f} with configured weights "
            f"and {p['reranker']:.2f} with the re-ranker (base rate {p['base_rate']:.2f})."
        )
    else:
        line = "The learning panel waits for verdicts of both kinds before it learns anything."
    bullets(
        s,
        0.85,
        5.3,
        11.8,
        1.6,
        [
            line,
            "Labels so far are planted synthetic cases and rule-seeded benign patterns: this shows the mechanism, not field precision. Nothing is applied automatically; the threshold simulator shows what a change would do first.",
        ],
        size=14,
    )
    footer(s, n)
    notes(
        s,
        "Be careful with the wording here: the precision is on planted and seeded labels. Real verdicts replace them as reviewers work.",
    )

    # 10. Honest evaluation
    n += 1
    s = blank(prs)
    header(s, "How we measured", "Planted anomalies, judged in each detector's own queue")
    names = {
        "inflated_cost": "Inflated cost",
        "duplicate": "Duplicate works",
        "fast_complete": "Implausibly fast completion",
        "split_group": "Split work",
    }
    rows = [k for k in ("inflated_cost", "fast_complete", "duplicate", "split_group") if k in inj]
    table = s.shapes.add_table(
        len(rows) + 1, 4, Inches(0.85), Inches(1.75), Inches(7.6), Inches(0.5 * (len(rows) + 1))
    ).table
    heads = ["Detector", "Fired on planted", "Found in top 5% of queue", "Top 10%"]
    for c, head in enumerate(heads):
        cell = table.cell(0, c)
        cell.text = head
        cell.fill.solid()
        cell.fill.fore_color.rgb = CARD
        para = cell.text_frame.paragraphs[0]
        para.runs[0].font.size = Pt(12)
        para.runs[0].font.bold = True
        para.runs[0].font.color.rgb = MUTED
    for r, key in enumerate(rows, start=1):
        values = [
            names[key],
            pct(inj[key]["detector_fired"]),
            pct(inj[key]["recall_at_top_5pct"]),
            pct(inj[key]["recall_at_top_10pct"]),
        ]
        for c, value in enumerate(values):
            cell = table.cell(r, c)
            cell.text = value
            cell.fill.solid()
            cell.fill.fore_color.rgb = NAVY if r % 2 else NAVY_DEEP
            run = cell.text_frame.paragraphs[0].runs[0]
            run.font.size = Pt(14)
            run.font.color.rgb = RED if key == "split_group" and c else WHITE
    proxy = m["supervised_model"]
    bullets(
        s,
        8.75,
        1.75,
        3.8,
        5.0,
        [
            f"Proxy-label model PR-AUC {proxy['pr_auc_oof']:.2f}: it learns the dataset's hand-written rule label, not verified fraud, so this measures learnability of rules.",
            f"Expected-cost model: typical error {m['expected_cost_model']['mae_as_cost_ratio']:.1f}x, R² {m['expected_cost_model']['r2']:.2f}, out of fold.",
            "Global top-5% recall targets from step 2b were not met for any detector; per-queue recall is the fair measure and is reported as it is.",
        ],
        size=13,
    )
    text(
        s,
        0.85,
        4.6,
        7.6,
        1.4,
        "Injection recall shows detector sensitivity to anomalies of the patterns we planted. Planted cases are cleaner than real ones, so these are an upper bound on how obvious such cases are, not a fraud detection rate.",
        size=13,
        color=MUTED,
    )
    footer(s, n)
    notes(
        s, "This slide is where we earn trust. Read the split-work row aloud and the proxy caveat."
    )

    # 11. Accountability and privacy
    n += 1
    s = blank(prs)
    header(s, "Accountability and privacy", "Built for a public repository and a public audience")
    items = [
        (
            "Presentation mode",
            "MP and vendor names become stable pseudonyms; beneficiary names and phone numbers in descriptions are masked. Every screenshot here was taken in it.",
        ),
        (
            "Audit trail",
            "Every status change, verdict, note, export and brief is appended to a SHA-256 hash chain; editing, deleting or re-hashing any event is detected.",
        ),
        (
            "Citizen view",
            "Public and read-only: what was sanctioned, spent and completed by district. No scores, no flags, no work ids.",
        ),
        (
            "Framing",
            "Alerts are hypotheses for review. MP views describe implementation by executing agencies. No rankings of people.",
        ),
    ]
    for i, (title, body) in enumerate(items):
        col, row = i % 2, i // 2
        x, y = 0.85 + col * 6.0, 1.75 + row * 2.5
        box(s, x, y, 5.7, 2.25, CARD, LINE)
        text(
            s,
            x + 0.25,
            y + 0.18,
            5.2,
            0.45,
            title,
            size=18,
            bold=True,
            color=SAFFRON_TEXT,
            font=TITLE_FONT,
        )
        text(s, x + 0.25, y + 0.7, 5.2, 1.5, body, size=14)
    footer(s, n)
    notes(s, "Mention the citizen view with a live click if time allows.")

    # 12. Limits and next steps
    n += 1
    s = blank(prs)
    header(s, "Limits and next steps", "What we would do with the ministry's data")
    bullets(
        s,
        0.85,
        1.75,
        5.8,
        5.0,
        [
            f"Split-work detection flags {pct(split['detector_fired'])} of planted groups: needs vendor identifiers and sanction-authority limits.",
            "Vendors are identified by name only (no PAN or GSTIN), so network links are name similarity.",
            "The extract has no release ledger or entitlement: fund flow and lapse are labelled estimates.",
            "No verified fraud labels: every model learns patterns or proxies, never ground truth.",
        ],
        size=15,
    )
    bullets(
        s,
        6.95,
        1.75,
        5.6,
        5.0,
        [
            "Link PFMS payments and sanction orders to close the ledger gaps.",
            "Collect reviewer verdicts in pilot districts; retrain the re-ranker on them.",
            "Add geotagged photos for completion checks on fast-completed works.",
            "Deploy behind government SSO with the same role scopes.",
        ],
        size=15,
        color=WHITE,
    )
    text(s, 0.85, 1.35, 5.8, 0.35, "LIMITS", size=12, color=AMBER, bold=True)
    text(s, 6.95, 1.35, 5.6, 0.35, "NEXT", size=12, color=GREEN, bold=True)
    footer(s, n)
    notes(s, "End on what is genuinely open. Judges respect a team that knows its weak spots.")

    # 13. Close
    n += 1
    s = blank(prs)
    box(s, 0, 0, 13.333, 7.5, NAVY, radius=False)
    text(s, 1.2, 2.2, 11, 1.0, "Thank you", size=54, bold=True, font=TITLE_FONT)
    text(
        s,
        1.2,
        3.3,
        11,
        1.2,
        "MPLADS Sentinel: risk indicators for review, with the evidence attached.\nLive demo: demo.ps1  ·  Citizen view: /public",
        size=20,
        color=MUTED,
    )
    notes(s, "Switch to the live demo.")

    prs.save(OUT)
    return OUT


if __name__ == "__main__":
    path = build()
    print(f"wrote {path} ({path.stat().st_size / 1e6:.1f} MB)")
