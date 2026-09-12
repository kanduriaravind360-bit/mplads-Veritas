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

---

# Live scoring: the exact sequence

Added in step 2e. Two sources, two different arguments. Run them in this order.

**Click:** Live Scoring in the sidebar.

## A. Synthetic demo works (0:00 — 1:00)

**Tab:** *Score demo works* → press the button. Thirteen invented works, scored
in about 9 seconds through the same code path as any upload. An amber badge on
the page reads "Synthetic demo works — not real records".

These are the numbers to expect. They will not move unless the pipeline is
re-run.

| What it is | Amount | Risk | Band |
|---|---|---|---|
| Stalled 2 years at "Sanction" | ₹12.50 L | **87.2** | High |
| Hand pump at 8x the going rate | ₹16.00 L | **78.4** | Medium |
| Split road, reach 4 | ₹9.97 L | 74.4 | Medium |
| Split road, reach 3 | ₹9.99 L | 72.9 | Medium |
| Split road, reach 2 | ₹9.98 L | 70.8 | Medium |
| Duplicate, original | ₹10.00 L | 65.3 | Medium |
| Split road, reach 1 | ₹9.98 L | 65.0 | Medium |
| Duplicate, reworded copy | ₹10.20 L | 62.8 | Low |
| Completed in 3 days, fully paid | ₹9.00 L | 61.2 | Low |
| Ordinary hand pump | ₹2.00 L | 24.5 | Low |
| Ordinary solar light | ₹20,944 | 22.6 | Low |
| Solar light at 2.5x the state median | ₹52,360 | **0.0** | Low |
| Ordinary CC road | ₹9.91 L | 0.0 | Low |

**What to say:**

> "Thirteen works it has never seen, scored in nine seconds. The three ordinary
> ones sit at the bottom, near zero. The stalled work and the eight-times-priced
> hand pump come out on top. The four split works cluster together in the
> seventies, and each one says it looks like the others."

**Then say the honest part, out loud:**

> "Two of these it did not catch, and we left them in.
>
> The solar light we priced at two and a half times the Uttar Pradesh median
> scores zero. The reason is instructive: the model predicted ₹53,451 for that
> work and it costs ₹52,360. Solar lights run to nearly three lakh in West
> Bengal, so fifty thousand rupees is unremarkable nationally. It is only
> expensive for Uttar Pradesh, and our cost model is national.
>
> The fast completion trips its rule at full strength but reaches only 61,
> because one rule on its own cannot cross the High threshold by design. Two
> independent signals can. That is a deliberate choice about false alarms."

## B. Real works never used in training (1:00 — 1:45)

**Tab:** *Score 100 never-seen works* → press the button.

> "Now the rigorous version. Before we fitted anything, we removed 27 whole
> constituencies, 3,890 works, five percent. Not five percent of rows: whole
> constituencies, because vendor and district history is computed within an
> area, so holding out a single row would leave its neighbours behind and the
> model would effectively have seen it.
>
> No model, and no peer median, has touched any of these."

**Click:** Model Performance to show the comparison.

| | Training | Holdout |
|---|---|---|
| Low | 80.0% | 81.0% |
| Medium | 15.0% | 15.3% |
| High | 4.0% | 2.5% |
| Critical | 1.0% | 1.2% |
| Delay ROC-AUC | 0.873 | **0.909** |
| Delay PR-AUC | 0.859 | **0.873** |

> "The band distribution is almost identical, and the delay model actually does
> slightly better on the held-out constituencies than on its own test split:
> 0.909 against 0.873. It is not memorising districts."

## C. Upload (optional, 15 seconds)

**Tab:** *Upload your own CSV*. There is a downloadable template, and it names
any missing columns rather than failing silently.

---

## Numbers to have in your head

| Thing | Value |
|---|---|
| Works scored | 77,312, of which 73,422 train and 3,890 holdout |
| Holdout | 27 whole constituencies, 5.03% |
| Demo works | 13, scored in about 9 s |
| Delay model | 0.873 train split, 0.909 holdout |
| Cost model | typical error 1.4x |
| Weakest detector | split works, 46% |

## If something fails on stage

- Live Scoring throws an error: the saved models are missing. Run
  `python -m ml.train` and reload.
- The demo table is empty: `demo_data/live_demo_works.csv` is missing.
- Holdout tab says no holdout found: same fix, `python -m ml.train` builds it.
