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
uv pip install torch --index-url https://download.pytorch.org/whl/cu128
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

**Step 1 — setup + data loading.** Python 3.12 environment on `uv` with the full
data/ML/API stack pinned and import-verified (24/24 modules). PyTorch is
installed from the CUDA 12.8 index for the RTX 5060. Private GitHub repo created
and pushed.

`ml/data.py` loads the `Data` sheet, parses the four date columns, coerces
numeric types, standardises `work_status` / `work_category`, and flags date-logic
errors without dropping rows, writing `data/processed/works.parquet`. Four
invariants are covered by `tests/test_data.py`: 77,312 rows, unique `work_id`,
`anomaly_score` reproducing exactly from the seven weighted flags, and
`anomaly_label == (anomaly_score >= 4)`.
