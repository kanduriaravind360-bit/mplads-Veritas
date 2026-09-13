# MPLADS Sentinel: 5-minute demo script

For the judging round. The dashboard runs in presentation mode, so MP and vendor
names are pseudonyms and private names in descriptions are masked.

## Before you start (5 minutes before)

```bash
powershell -ExecutionPolicy Bypass -File demo.ps1 -Smoke
powershell -ExecutionPolicy Bypass -File demo.ps1
```

The smoke run proves the stack answers end to end. The real run guarantees the
three demo scenarios, resets the Bhatpara CCTV alerts to **Open** so the live
review step works, and opens http://127.0.0.1:4173.

Keep these tabs ready:

| Tab | URL | Signed in as |
|---|---|---|
| 1 | `/login` | nobody yet |
| 2 | `/public` | nobody (citizen view) |

Demo password for every account: `demo123`. If anything fails on stage, switch
to the deck: slides 4 to 9 are screenshots of the same screens.

The three scenarios, all real works from the data:

| Scenario | Where | What it shows |
|---|---|---|
| Bhatpara CCTV, `WS/MP18249/2025-2026/187617` and `/187616` | Alerts inbox | A Critical flag a reviewer can **clear**: different police stations and wards, and the cost model priced CCTV against computers |
| Madurai split group, 12 road works, ₹1.19 crore | Cases | A textbook split pattern: same agency, same day, each just below a round amount, 8.0 times the peer 90th percentile together |
| Bokaro | Risk map, Delays | 450 open works, mean delay probability 0.996 |

---

## 0:00 to 0:30 · The promise

**Tab 1.** Click **Ministry** under Demo accounts, then **Sign in**.

> "MPLADS Sentinel reads all 77,312 works in the public eSAKSHI extract and gives
> each one a risk indicator with its evidence attached, for a human reviewer. We
> never call anything fraud. Access is scoped: a ministry, a state, a district
> office and an MP each see exactly their own works."

## 0:30 to 1:10 · Command Centre

**Point at** the six KPI cards, then the blue strip under the title.

> "₹4,742 crore sanctioned. 6,456 works, 8.4%, are High or Critical, which is
> ₹1,085 crore of value to review first. The bands are percentiles, so the queue
> stays a size a district can work. Every rate carries its denominator.
>
> This strip is on every page: these are risk indicators, and our weakest
> detector, split-work detection at 46%, is stated right here, not hidden."

**Hover** any rupee figure to show the exact amount in words.

## 1:10 to 2:20 · Review an alert live (the Bhatpara CCTV case)

**Click** Alerts Inbox. Press **j** twice and **k** once to show keyboard triage.
Then press **Ctrl K**, type `187617`, and pick the entry under **Alerts Inbox**
(the one under Works opens the work page instead).

> "A Critical alert: CCTV cameras for Bhatpara police station, ₹41.5 lakh."

In the drawer:

1. **Explanation** tab: read the first reason, then click **हिन्दी**.
   > "Every reason is generated in English and Hindi."
2. **What would clear this** tab:
   > "It tells the reviewer which evidence the score rests on, and the check that
   > would resolve each piece."
3. **Evidence** tab: point at the description and the ward range.
   > "Its near-twin, 187616, is a different police station and wards 18 to 35.
   > These are two scopes, not a duplicate. And the cost flag came from grouping
   > CCTV with computers and smart classes."
4. **Review** tab: type *"Separate police stations and ward ranges; CCTV priced
   against computers."* Click **Under Review**, then **False positive**.
5. **Audit trail** tab:
   > "Every action is on a SHA-256 hash chain. Change one past event and
   > verification fails."

## 2:20 to 3:00 · Split work and a case

**Click** Duplicate Finder, then the **Split-work groups** tab. Point at the
amber banner.

> "Split groups are our weakest detector, and the page says so."

**Click** Cases, then open *Possible split work: Road / Pavement in MADURAI*.

> "Twelve road works from one agency, sanctioned the same day, each just below a
> round amount, together eight times the 90th-percentile cost of one such work. The case
> holds the summary, the linked alert and the notes, and prints a PDF brief for
> the agency."

Click **PDF brief** (it downloads; no need to open it).

## 3:00 to 3:40 · Where delays are building up

**Click** Risk Map. Switch **Colour by** to **Delay risk**. Hover **Bokaro**.

> "Bokaro: 450 open works and a delay probability close to one. The delay model
> scores 0.909 ROC-AUC on 27 whole constituencies we removed before training."

**Click** Delays & Early Warning and point at the fund-lapse chart's **Estimate**
tag.

> "Where the data has no ledger we say it is an estimate."

## 3:40 to 4:20 · Tuning without breaking anything

**Click** Threshold Simulator. Drag **Duplicate** from 0.22 to about 0.40.

> "A what-if on the stored detector channels: the queue changes by this much,
> this many works enter, this many leave. Nothing is saved."

Click **Reset to configured**. Then click **Learning**.

> "Verdicts like the one I just recorded re-weight the detectors, and the effect
> is measured on labels held back from learning. Today those labels are planted
> synthetic cases and rule-seeded benign patterns, so this shows the mechanism,
> not field precision, and the page says exactly that."

## 4:20 to 4:45 · Scope and the citizen view

**Sign out.** Click **MP** under Demo accounts and sign in. Open **MP Portfolio**.

> "An MP sees implementation risk of works recommended in their constituency,
> described as delivery by executing agencies, never a judgement of the Member.
> No reviewer tools, no rankings."

**Switch to tab 2** (`/public`), pick any district.

> "And citizens see where the money went: sanctioned, spent, completed. No scores
> and no flags on individual works."

## 4:45 to 5:00 · Close

> "MPLADS Sentinel: every flag with its evidence, honest about its limits, scoped
> to each role, and on a tamper-evident trail. Thank you."

---

## If a judge asks for more

- **Model Performance** page: per-detector recall, the proxy-label caveat, and
  holdout against training band shares.
- **Data Ingest**: upload `demo_data/live_demo_works.csv` and click **Validate
  and score** (no commit needed).
- **Light theme and Hindi UI**: the sun icon and the हि button in the top bar.

Answers to likely questions are in [JUDGE_QA.md](JUDGE_QA.md).
