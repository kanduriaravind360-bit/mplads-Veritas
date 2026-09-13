# MPLADS Sentinel

**Smart India Hackathon 2026 — Problem Statement 26102 (MoSPI)**

MPLADS Sentinel is an AI platform that flags anomalies, fraud risk, delays and
duplicate works in MPLADS (Member of Parliament Local Area Development Scheme)
data. It ingests the public eSAKSHI works extract — 77,312 real works across
both houses of Parliament — scores each work against statistical, rule-based and
learned detectors, and serves the results through a FastAPI backend and a React
dashboard with separate views for the Ministry, State Nodal Authorities,
District Authorities and Members of Parliament. Everything it surfaces is a
**risk indicator for human review**, not proof of fraud; MP-level views describe
the implementation risk of works recommended in a constituency, never a
judgement of the MP.

## What it does

- **Review queue with evidence.** Every work gets a 0-100 risk score from six
  channels: rules, a proxy model, unsupervised anomaly, expected cost, duplicate
  or split, and delay. It comes with reasons in English and Hindi, peer cost
  comparisons, and "what would clear this".
- **Workflow a ministry can audit.** Alerts move through review, verdicts,
  escalation and investigation cases with PDF briefs. Every action is on a
  SHA-256 hash chain.
- **Four scoped roles.** Ministry, state, district office and MP each see exactly
  their own works. MP views describe implementation risk of works recommended in
  the constituency, never a judgement of the Member.
- **Dashboard pages:**
  - review: Command Centre, Risk Map, Money at Risk, Alerts, Work detail,
    Duplicates and splits, Vendor network, Cases
  - monitoring: Delays, Compliance, Trends, MP Portfolio
  - model and data: Model Performance, Threshold Simulator, Learning from
    reviewers, Data Ingest
  - a public citizen view with no per-work risk
- **Honest by construction.** Numbers on screen and in the deck come from
  `models/metrics.json` and the database. The proxy-label caveat and the weakest
  detector are on every analytical page.

| Measure | Result |
|---|---|
| Works scored | 77,312 (₹4,742 crore sanctioned) |
| Review queue (High + Critical) | 6,456 works, 8.4%; ₹1,085 crore of value |
| Planted inflated cost found in top 5% of its queue | 79% |
| Planted duplicates found in top 5% of their queue | 45% |
| Planted split-work groups flagged at all | **46%, our weakest detector** |
| Delay model on 27 held-out constituencies | ROC-AUC 0.909, PR-AUC 0.873 |
| Proxy-label model (learns the rule label, not fraud) | PR-AUC 0.935 out of fold |

Docs: [5-minute demo script](docs/DEMO_SCRIPT.md) ·
[judge Q&A](docs/JUDGE_QA.md) · [code walkthrough](docs/CODE_WALKTHROUGH.md) ·
deck `presentation/MPLADS_Sentinel_SIH26102.pptx` (rebuild with
`python presentation/build_deck.py`).

## Quick start (demo)

On Windows, after the setup below, one command builds whatever is missing, loads
the database, guarantees the demo scenarios, and starts the API and dashboard:

```bash
powershell -ExecutionPolicy Bypass -File demo.ps1
```

It opens http://127.0.0.1:4173 with names pseudonymised (`-RealNames` turns that
off, for private screens only). `-Smoke` starts everything, checks a real login
through the dashboard's proxy, then stops. On Linux or macOS, `make demo` runs
the same steps. `docker compose up --build` is provided but **untested**: Docker
is not installed on the build machine, so `demo.ps1` is the verified path.

## Setup

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), and Node.js 20 or later
for the dashboard.

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
uv pip install torch==2.9.0+cu128 --index-url https://download.pytorch.org/whl/cu128
```

The `cu128` index is required — RTX 50-series (Blackwell, `sm_120`) GPUs will not
run on older CUDA wheels.

Build the cleaned dataset:

```bash
python -m ml.data
```

Run the whole ML pipeline (about 3 minutes on an RTX 5060):

```bash
python -m ml.train
```

The step-2c Streamlit prototype (`streamlit run demo_app.py`) still works but is
superseded by the React dashboard below.

Load the results into the application database and start the API (OpenAPI docs
at http://127.0.0.1:8000/docs):

```bash
python -m backend.app.loader
uvicorn backend.app.main:app --port 8000
```

Demo users, all with password `demo123`: `ministry@demo`, `state.up@demo`
(Uttar Pradesh), `district.lucknow@demo` (Lucknow district office) and
`mp.0147@demo` (MP code 147). Set `JWT_SECRET` before any deployment, and
`PRESENTATION_MODE=1` for any screenshot, deck or public link: it replaces MP and
vendor names with stable pseudonyms in every API response.

Optional extras for the learning panel and the weekly digest:

```bash
python -m ml.planted                  # planted synthetic cases (about 3 minutes on GPU)
python -m backend.app.loader          # loads them into their own table
python -m backend.app.learning_seed   # rule-seeded demo verdicts; never "confirmed" on a real work
python -m backend.app.digest          # writes outbox/digest-<date>-all-india.html
```

Start the dashboard (React, served on http://127.0.0.1:5173 with `/api` proxied
to the API):

```bash
npm --prefix frontend install
npm --prefix frontend run dev
```

Run the checks:

```bash
ruff check . && pytest
npm --prefix frontend run typecheck && npm --prefix frontend test
npm --prefix frontend run e2e
```

The end-to-end suite builds the production bundle, logs in as each of the four
roles, visits every page, fails on any console error, checks scoping, and writes
screenshots to `presentation/assets/screens/`. It refuses to run unless the API
reports presentation mode, because those screenshots are committed.

> **Note on pinned versions.** This machine runs Windows Smart App Control in
> enforced mode, which blocks compiled extension DLLs with no established
> reputation. The numpy / scipy / scikit-learn / pandas pins in `pyproject.toml`
> are mature builds that load cleanly. See `CLAUDE.md` before bumping them.

## Layout

| Path | Contents |
|---|---|
| `data/raw/` | Source eSAKSHI workbook (committed; public data, public repo) |
| `data/processed/` | Parquet artefacts (gitignored) |
| `configs/` | YAML thresholds and mappings |
| `ml/` | Data loading, features, detectors, models |
| `backend/` | FastAPI service, loader, seeds, digest |
| `frontend/` | React dashboard and Playwright end-to-end tests |
| `models/` | `metrics.json` and scoring context (trained artefacts are gitignored) |
| `presentation/` | Deck builder, the deck, and pseudonymised screenshots |
| `docs/` | Demo script, judge Q&A, code walkthrough |
| `deploy/`, `docker-compose.yml` | Container setup (untested) |
| `scripts/` | One-off builders, such as the district boundary file |
| `demo.ps1`, `Makefile` | One-command demo (the PowerShell script is the verified path) |
| `tests/` | pytest suite |

## Progress

**Step 1 — setup + data loading.** Python 3.12.10 environment on `uv` with the
full data/ML/API stack pinned and import-verified (29/29 modules). PyTorch
2.9.0+cu128 runs on the RTX 5060 Laptop GPU (`sm_120`, 8.55 GB, 3.6 TFLOP/s fp32
on a 4096² matmul); XGBoost trains with `device="cuda"`. GitHub repo
created and pushed.

`ml/data.py` loads the `Data` sheet, parses the four date columns, coerces
numeric types, standardises `work_status` / `work_category`, and flags date-logic
errors without dropping rows, writing `data/processed/works.parquet`. Four
invariants are covered by `tests/test_data.py`: 77,312 rows, unique `work_id`,
`anomaly_score` reproducing exactly from the seven weighted flags, and
`anomaly_label == (anomaly_score >= 4)`.

**Step 2 — ML pipeline + risk scoring.** `python -m ml.train` runs the whole
thing end to end. It derives a real work type from the description (26 Hinglish
keyword rules covering 80.7% of works, plus GPU sentence-embedding clustering for
the rest), builds 33 leak-safe features on robust peer-group statistics, and runs
four detectors: Isolation Forest + ECOD, duplicate and split-work detection,
a delay model, and a proxy-label model.

Every work gets a 0-100 `risk_score` with bilingual plain-language reasons, plus
state, district, constituency and vendor roll-ups. Leakage is enforced in code by
`ml.features.assert_leak_safe` and tested. The proxy-label model's PR-AUC measures
how learnable the hand-written rules are, **not** fraud detection; the caveat
ships inside `models/metrics.json`. Full run: 165 seconds on an RTX 5060.

**Step 2b — improved detectors + calibrated risk bands.** The cost signal is now
an expected-cost model rather than a peer-group statistic: it predicts
`log(sanction_amount)` from work type, state, quantities parsed from the
description and the embedding reduced by SVD, out-of-fold so no work prices
itself. MAE is 0.340 log-rupees, a typical error of 1.4x, R² 0.768.

Duplicate detection replaced a chain of hard gates with a weighted pair score
over nearest-neighbour candidates, and split detection made vendor identity
optional. Risk bands became percentile cut-offs, fixing the review queue at 1%
Critical and 4% High.

The headline evaluation is now **per detector queue**, because a reviewer opens
one queue at a time rather than a single global list, and the global list is
dominated by 9,239 real in-constituency duplicates and 2,686 genuinely fast
completions that correctly outrank a reworded plant.

| Detector | Fired | Queue | Recall @1% | @5% | @10% |
|---|---|---|---|---|---|
| Fast completion | 100.0% | 3,527 | 6.7% | 100.0% | 100.0% |
| Inflated cost | 96.7% | 9,302 | 0.0% | 78.7% | 94.7% |
| Duplicates | 73.3% | 19,220 | 0.0% | 45.3% | 55.3% |
| Split works | 46.0% | 7,196 | 0.0% | 5.4% | 46.0% |

The split-work detector is our weakest at 46% and is the main open item. Global
rank recall is kept in `models/metrics.json` for continuity, labelled as
misleading. Precision inside each queue counts only planted cases as hits, so a
genuine anomaly ranked high scores as a miss; read it as a floor.

**Step 2c — Streamlit demo app.** `streamlit run demo_app.py` opens a seven-page
presentation app over the pipeline output: overview, risk explorer with a
per-work evidence panel, top risks, duplicates and split works, delay early
warning, model performance, and live scoring of an uploaded CSV. It reads the
saved artefacts only and never retrains, so it opens in about a second.

The Model Performance page carries the caveats rather than hiding them: the
proxy-label warning and the split-work detector at 46%. This is a temporary demo
for the hackathon round; the role-based dashboard comes later.

**Step 2e — live-scoring demo data + holdout.** Two ways to score works the
system has never seen, both through the same code path as any upload.

`demo_data/live_demo_works.csv` holds 13 invented works, clearly badged as
synthetic, built to exercise each detector. Scored in about 9 seconds.

A **5% holdout** is reserved before anything is fitted: 27 whole constituencies,
3,890 works, listed in `configs/holdout.yaml`. Whole constituencies rather than
rows, because vendor and district history is computed within an area, so holding
out a single row would leave its neighbours in training. The delay model scores
**0.909 ROC-AUC on the holdout against 0.873** on its own test split, and the
band distribution barely moves (81.0% Low against 80.0%), so it is not
memorising districts.

Three fixes fell out of building this: uploads were banding against percentiles
of their own batch, the expected-cost model was being refit per upload rather
than reused, and `score_new_works` rebuilt features from the wrong frame.

**Step 3a — severe-rule floor, state-relative cost, split routing.** One severe
rule (completed and fully paid within a day, stalled at an early stage for 612+
days, or payment stuck) now lifts a work to at least the High cut-off, two to
Critical. That lifts 2,539 works; High plus Critical goes from 5.0% to 8.4% of
the 73,422 training works, above the ~7% expected, because stalled works add
1,437. The per-detector injection recall and the holdout delay AUCs are
unchanged; global rank recall falls (split groups 21.6% to 12.2%), which is the
arithmetic of lifting 2,539 works above planted cases.

The state-relative cost channel was built, measured and **kept out of the
score**: driving the cost signal with it cut cost recall in its own queue from
78.7% to 61.3%, and a non-saturating mapping still only reached 60.7%. It
remains as descriptive data (`state_cost_ratio`) for the peer-comparison view.
Uploads now look up saved peer statistics and search for split groups across the
upload plus existing works in the same district, so the four demo road pieces
are named a split work, with their 98% description similarity kept as supporting
evidence. Uploads also count ages to the national data cut-off rather than the
upload's own latest date.

**Step 3b — backend API.** FastAPI, SQLAlchemy 2 and Pydantic v2 on SQLite
(Postgres via `DATABASE_URL`). The loader brings in all 77,312 works, 10,749
alerts (including 251 from the holdout), 69,174 duplicate pairs and 1,004 split
groups in about 30 seconds, and a reload keeps reviewers' statuses and history.
60 operations cover overview, works, alerts, duplicates, splits, vendor network,
compliance, predictions, geo, analytics, models, ingest, PDF briefs, cases, a
public citizen view, and a nightly re-score and escalation scheduler.

Row-level scoping sits in one place and applies to every query, export, report
and upload; an out-of-scope id answers 404, so the API does not confirm it
exists. On the real data the Lucknow reviewer sees 270 works and 76 alerts, and
asking for another state returns nothing. The audit trail is a SHA-256 hash
chain, and tests show that editing, deleting or re-hashing any past event is
detected. 88 API tests run on a synthetic database with invented names.

**Step 3c — dashboard.** React 18, Vite, strict TypeScript, Tailwind and Radix
primitives in a navy command-centre design, with English and Hindi, dark and
light themes, a Ctrl K palette that searches works, alerts and districts, and
Indian lakh/crore figures that show the exact amount in words on hover. Twelve
pages run on live API data: Command Centre, Risk Map, Alerts Inbox (j/k/e
triage and an evidence drawer), Work Detail, Duplicate Finder, Vendor Network,
Delays, Compliance, Trends, MP Portfolio, Model Performance and Data Ingest.
Every panel has designed loading, empty and error states.

The Risk Map joins districts by state and name through
`configs/district_aliases.yaml`, placing 99.3% of works; the rest are counted in
a footnote. The proxy-label caveat and the 46% split-work weakness appear on
every analytical page, read from the metrics rather than typed. Presentation
mode now also masks private beneficiary names and phone numbers in descriptions
(13,195 of 77,312 descriptions touched).

Eight Playwright tests log in as each role, visit every page with no console
errors, and check scoping: the Lucknow officer sees only Lucknow, an MP sees
only their own constituency and no reviewer tools, and an out-of-scope work is
a 404. The run writes 31 pseudonymised screenshots.

**Step 3d — review tools and learning.** Investigation cases group alerts,
carry notes and a status, and print a PDF brief. "What would clear this" breaks
a work's score into the evidence it rests on and states the check that would
resolve each piece, such as "sanctioned amount at or below Rs 79.72 lakh
against Rs 2.00 crore now". Money at Risk is a state and district treemap with
denominators. The threshold simulator re-fuses the stored channels with the
pipeline's own code. At the configured weights it reproduces every training
score (largest difference 0.005, all bands identical), and a Reset restores
them.

Learning from reviewers uses 256 planted synthetic positives and 157 negatives
seeded by documented benign rules: purchases completing quickly, catalogue-item
duplicates, and the Bhatpara CCTV pair, whose two police stations and ward
ranges differ. No real work is ever seeded as confirmed. On 110 held-back
labels, precision at 50 is 0.94 with configured fusion and 0.96 after Bayesian
re-weighting and after the logistic re-ranker, against a 0.64 base rate. That
shows the mechanism working, not field precision, and the page says so.

The public citizen view lists districts by implementing agency, with no scores,
flags or work ids, and a weekly digest is written to `outbox/`. The anomaly time
machine was not built. 11 end-to-end tests pass.

**Step 3e — demo path and hardening.** `demo.ps1` is the verified one-command
demo, and its `-Smoke` run signs in through the dashboard proxy and sees 77,312
works. `python -m backend.app.demo_seed` guarantees the three demo scenarios
from loaded data:

- the Madurai split-work case (12 works, Rs 1.19 crore)
- the Bhatpara CCTV alerts, reset to Open on the audit trail
- Bokaro, whose 450 open works all sit above the delay threshold

It exits non-zero if any scenario is missing, rather than drifting.

A Makefile, docker-compose, Dockerfiles and `.env.example` are included and
untested. `pyproject.toml` now declares the packages the API had only been
installed with (PyJWT, APScheduler, fpdf2), so a fresh clone installs cleanly.

Unhandled server errors return a reference ID instead of a traceback. The
dashboard shows a banner when the API is unreachable and a reload prompt for a
stale bundle, and two new end-to-end tests break the API in the browser and
watch it recover.

**Step 3f — deck and docs.** `presentation/build_deck.py` generates the
13-slide pitch deck, `MPLADS_Sentinel_SIH26102.pptx`, with speaker notes. It
reads every figure from `models/metrics.json` and the database at build time and
places the pseudonymised screenshots. The split-work weakness and the
proxy-label caveat each have space on a slide.

The docs add a five-minute demo script built on the three guaranteed scenarios,
twenty judge questions answered with measured numbers, and a code walkthrough
that follows one work from the spreadsheet to a reviewer's verdict.
