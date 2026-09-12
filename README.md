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

## Setup

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), and Node.js LTS (for the
frontend from step 4 onward).

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

Run the checks:

```bash
ruff check . && pytest
```

> **Note on pinned versions.** This machine runs Windows Smart App Control in
> enforced mode, which blocks compiled extension DLLs with no established
> reputation. The numpy / scipy / scikit-learn / pandas pins in `pyproject.toml`
> are mature builds that load cleanly. See `CLAUDE.md` before bumping them.

## Layout

| Path | Contents |
|---|---|
| `data/raw/` | Source eSAKSHI workbook (committed — private repo) |
| `data/processed/` | Parquet artefacts (gitignored) |
| `configs/` | YAML thresholds and mappings |
| `ml/` | Data loading, features, detectors, models |
| `backend/` | FastAPI service |
| `frontend/` | React dashboard |
| `models/` | Trained artefacts (gitignored) |
| `presentation/` | SIH pitch material |
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
