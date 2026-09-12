"""PDF review briefs for an alert, a case or a district.

Every brief carries the review framing, the evidence, the alert or case audit
trail with hashes, and the result of verifying the whole chain at the moment of
printing plus the chain's head hash. Printing that head hash anchors the trail:
anyone holding the paper can later check the database has not been rewritten.

Briefs are English only. The standard PDF fonts cannot shape Devanagari, and a
brief with broken Hindi conjuncts is worse than one that says so.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fpdf import FPDF

from backend.app.redact import enabled as presentation_mode

NAVY = (11, 31, 58)
SAFFRON = (197, 90, 17)
GREY = (90, 98, 110)


def _text(value: Any) -> str:
    """The core PDF fonts are Latin-1; replace anything else rather than crash."""
    text = "" if value is None else str(value)
    text = text.replace("₹", "Rs ").replace("—", "-").replace("–", "-")
    return text.encode("latin-1", "replace").decode("latin-1")


def inr(amount: float | None) -> str:
    if amount is None:
        return "-"
    if amount >= 1e7:
        return f"Rs {amount / 1e7:,.2f} crore"
    if amount >= 1e5:
        return f"Rs {amount / 1e5:,.2f} lakh"
    return f"Rs {amount:,.0f}"


class Brief(FPDF):
    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self._title = title
        self._subtitle = subtitle
        self.set_auto_page_break(auto=True, margin=16)
        self.set_margins(16, 16, 16)
        self.add_page()

    def header(self) -> None:
        self.set_fill_color(*NAVY)
        self.rect(0, 0, 210, 20, style="F")
        self.set_xy(16, 6)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 13)
        self.cell(0, 8, _text("MPLADS Sentinel - review brief"), new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(8)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*GREY)
        self.cell(
            0,
            6,
            _text(f"Risk indicators for review, not findings of fraud. Page {self.page_no()}"),
            align="C",
        )

    def title_block(self) -> None:
        self.set_font("Helvetica", "B", 16)
        self.multi_cell(0, 8, _text(self._title), new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*GREY)
        stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        mode = " | presentation mode: names pseudonymised" if presentation_mode() else ""
        self.multi_cell(
            0,
            5,
            _text(f"{self._subtitle} | generated {stamp}{mode}"),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.set_text_color(0, 0, 0)
        self.ln(2)
        self.set_fill_color(253, 243, 231)
        self.set_draw_color(*SAFFRON)
        self.set_font("Helvetica", "", 9)
        self.multi_cell(
            0,
            5,
            _text(
                "This brief lists risk indicators for a human reviewer. It is not a finding "
                "of fraud or wrongdoing by any person. Where an MP is named, figures describe "
                "the implementation of works recommended in the constituency, not the MP."
            ),
            border=1,
            fill=True,
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.ln(3)

    def section(self, heading: str) -> None:
        self.ln(2)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*NAVY)
        self.cell(0, 7, _text(heading), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*SAFFRON)
        self.line(16, self.get_y(), 194, self.get_y())
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def fields(self, pairs: list[tuple[str, Any]]) -> None:
        for label, value in pairs:
            self.set_font("Helvetica", "B", 9)
            self.cell(48, 5.5, _text(label))
            self.set_font("Helvetica", "", 9)
            self.multi_cell(0, 5.5, _text(value), new_x="LMARGIN", new_y="NEXT")

    def bullets(self, items: list[str]) -> None:
        self.set_font("Helvetica", "", 9)
        for item in items:
            self.multi_cell(0, 5, _text(f"- {item}"), new_x="LMARGIN", new_y="NEXT")

    def table(self, headers: list[str], rows: list[list[Any]], widths: list[float]) -> None:
        self.set_font("Helvetica", "B", 8)
        self.set_fill_color(234, 238, 244)
        for header, width in zip(headers, widths, strict=True):
            self.cell(width, 6, _text(header), border=1, fill=True)
        self.ln()
        self.set_font("Helvetica", "", 8)
        for row in rows:
            for value, width in zip(row, widths, strict=True):
                text = _text(value)
                max_chars = int(width * 1.9)
                self.cell(
                    width,
                    5.5,
                    text[:max_chars] + ("..." if len(text) > max_chars else ""),
                    border=1,
                )
            self.ln()

    def chain(self, trail: list[dict[str, Any]], chain_report: dict[str, Any]) -> None:
        self.section("Audit trail (hash-chained)")
        if trail:
            self.table(
                ["#", "When (UTC)", "Actor", "Action", "Hash"],
                [
                    [e["seq"], e["ts"][:19], e["actor"], e["action"], e["hash"][:16] + "..."]
                    for e in trail
                ],
                [10, 36, 50, 36, 46],
            )
        else:
            self.bullets(["No review actions recorded yet."])
        self.ln(2)
        status = (
            "VERIFIED"
            if chain_report.get("ok")
            else f"BROKEN at event {chain_report.get('first_broken_seq')}"
        )
        self.fields(
            [
                ("Chain check", f"{status} ({chain_report.get('events_checked')} events)"),
                ("Chain head hash", chain_report.get("head_hash") or "-"),
            ]
        )
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*GREY)
        self.multi_cell(
            0,
            4.5,
            _text(
                "Keep this head hash. Recomputing the chain later and reaching the same hash "
                "shows no recorded action before this brief was altered or removed."
            ),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.set_text_color(0, 0, 0)


def render(pdf: Brief) -> bytes:
    return bytes(pdf.output())
