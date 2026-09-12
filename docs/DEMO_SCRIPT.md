# MPLADS Sentinel — 3-minute demo script

For the hackathon round. Run this first, then leave the browser open:

```bash
streamlit run demo_app.py
```

Two real works from the data carry the whole demo. Have both ready.

| # | What it shows | Where |
|---|---|---|
| **SPL00001** — Madurai, 12 road works | A textbook split pattern | Duplicates & Split Works |
| **WS/MP18249/2025-2026/187616 / 187617** — Bhatpara CCTV | A flag a reviewer can *clear* | Risk Explorer |

---

## 0:00 — 0:30 · Overview

**Click:** Overview (opens here).

> "This is MPLADS Sentinel. It reads 77,312 real MPLADS works from the public
> eSAKSHI data, covering 2023 to 2026, and gives every one of them a risk score
> with the evidence attached.
>
> Of those, about 3,900 come out as High or Critical. That is 5%, which is a
> queue a district office can actually work through. Everything you see is a
> **risk indicator for review**. We never call anything fraud."

**Point at the monthly chart.**

> "The amber bars are March. Sanctions spike at the financial year end, which is
> exactly when rushed paperwork and weak costing show up."

---

## 0:30 — 1:15 · The strongest finding: a split work

**Click:** Duplicates & Split Works → *Split-work groups* tab. **SPL00001 is at the top.**

> "Twelve road works. One district, Madurai. All sanctioned on the same day,
> the 13th of September 2024. Look at the amounts."

**Read two or three aloud: ₹9,95,109 · ₹9,95,995 · ₹9,96,186.**

> "Every one sits just under ten lakh. Together they come to ₹1.19 crore, while
> a typical single road work in that peer group is about ₹9.96 lakh.
>
> Twelve works each a whisker below a round threshold, same district, same day.
> That is the shape of one large work broken up. We are not saying it is. We are
> saying a human should look, and here is everything they need to decide."

---

## 1:15 — 2:00 · A flag the reviewer can clear

**Click:** Risk Explorer. **Filter State = West Bengal, band Critical. Select `WS/MP18249/2025-2026/187617`.**

> "This one scores 99. Same amount as its neighbour, ₹41.5 lakh, sanctioned the
> same day, 97% similar text. The duplicate detector flagged it."

**Point at the reasons panel, English and Hindi side by side.**

> "Now read the descriptions. One covers Jagaddal police station, wards 18 to 35.
> The other covers Bhatpara police station, wards 1 to 17. Different areas.
> This is a legitimate pair, not a duplicate."

> "That is the point. The reviewer cleared it in about ten seconds, because the
> evidence was on the screen next to the score. A system that just says '99, look
> into it' wastes their day. We show our work, in English and in Hindi."

---

## 2:00 — 2:30 · Delay early warning

**Click:** Delay Early Warning.

> "This is the forward-looking half. For every ongoing work we predict the chance
> it will not finish within a year of sanction, using only what was known at
> sanction time: the amount, the work type, and how that district and vendor
> performed on earlier works. No information from the future.
>
> It scores 0.87 ROC-AUC on later sanctions than it was trained on. That is money
> a State Nodal Authority can chase before the year is lost, not after."

---

## 2:30 — 3:00 · What we are not claiming

**Click:** Model Performance. **Scroll to the two amber boxes.**

> "Two things we put on the screen rather than hide.
>
> First, our split-work detector is the weakest at 46%. It finds fewer than half
> the planted test cases. That is our main open item.
>
> Second, the risk model's PR-AUC of 0.935 is not a fraud detection rate. Its
> target is a hand-written rule, not a verified fraud case, so that number means
> the rules are reproducible from observable data. Nothing more."

> "We test this by planting 600 known anomalies in a copy of the data and
> re-running the detectors blind. Cost inflation is caught 96.7% of the time,
> fast completion 100%, duplicates 73%, splits 46%.
>
> One last thing. The data has real MP names in it. We never rank MPs. A
> constituency view says 'implementation risk of works recommended here', because
> that is a statement about the agencies doing the work, not about the Member."

---

## If you have 30 seconds more

**Click:** Live Scoring → *Sample 100 unseen works*.

> "Scored live with the saved models. Nothing retrained. This is what a district
> officer gets when they upload next month's extract."

## Fallback if something fails

- App will not start, or a page is blank: the pipeline output is missing. Run
  `python -m ml.train` (about 3 minutes) and reload.
- Live Scoring errors on an uploaded CSV: use the *sample 100* button instead;
  it needs the same columns as the source extract.
- Numbers differ slightly from this script: the pipeline was re-run. The story
  does not change; read the figures off the screen.
