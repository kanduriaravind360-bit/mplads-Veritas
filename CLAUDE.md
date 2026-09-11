# CLAUDE.md — MPLADS Sentinel

## Project

**MPLADS Sentinel** — Smart India Hackathon 2026, **Problem Statement 26102**
(Ministry of Statistics and Programme Implementation).

An AI platform that flags **anomalies, fraud risk, delays and duplicate works**
in MPLADS (Member of Parliament Local Area Development Scheme) data, with a
**FastAPI backend** and a **React dashboard** serving four roles: Ministry,
State, District and MP.

Source data: real public eSAKSHI data, Lok Sabha + Rajya Sabha,
**77,312 works × 34 columns**, one row per work.

Built in **7 steps**.

Hardware: Windows 11, NVIDIA RTX 5060 (Blackwell, 8 GB VRAM), Intel i7-14700HX.

---

## Rules for every step

### 1. Do only the step I give you

Do not start other steps. Do not scaffold future work "while you're in there".
If a step is ambiguous, make the routine call yourself and state the assumption.

### 2. When a step is done

- `ruff check .` and `pytest` must pass.
- Add 2–3 lines to the **Progress** section of `README.md`.
- Commit as `step N: <summary>`.
- Push to `main`.
- Tag `step-N`.
- **Never commit secrets. Never force-push.**

### 3. LEAKAGE RULE

`anomaly_label` is a **proxy label**, not verified fraud:

```
anomaly_score = 2*flag_sanction_delay + 3*flag_stuck_work + 3*flag_cost_outlier
              + 2*flag_fast_completion + 1*flag_round_amount
              + 3*flag_vendor_concentration + 1*flag_payment_stuck
anomaly_label = (anomaly_score >= 4)
```

Therefore **`flag_*`, `anomaly_score` and `flag_reasons` must never be model
input features.** Using them is pure label leakage and yields a meaningless
perfect score. They are carried in the data for auditing only;
`ml.data.LEAKY_COLUMNS` names them.

The raw columns the rules are computed *from* — `cost_zscore`,
`days_to_sanction`, `duration_days`, `days_since_sanction`,
`vendor_work_count` — **are** legitimate features. But any model trained on the
proxy label is learning to reproduce a hand-written rule set, not to detect real
fraud, and must say so wherever its results are reported.

### 4. Honesty

- Results are **"risk indicators for review"**, never proof of fraud. Every
  surfaced item is a hypothesis for a human reviewer, with its evidence attached.
- The data contains **real MP names and constituencies**. MP views show
  **"implementation risk of works recommended in this constituency"** — a
  statement about implementation by executing agencies, **never** a judgement of
  the MP. No "most corrupt MP" style rankings, ever.
- Always show the denominator. A district with 3 works and 1 flag is not
  "33% anomalous".
- If a result is weak, say it is weak. Do not inflate numbers in the pitch.

### 5. Engineering

- **GPU (CUDA) for torch / sentence-transformers, with CPU fallback.** RTX
  50-series needs **cu128** wheels
  (`uv pip install torch --index-url https://download.pytorch.org/whl/cu128`).
  XGBoost/LightGBM use `device="cuda"` when available, falling back to CPU.
  scikit-learn uses `n_jobs=-1`.
- **Seed 42** everywhere.
- **Thresholds live in `configs/*.yaml`**, never hard-coded. Read them through
  `ml.config.load_config`.
- Typed Python, small modules. Notebooks are for exploration only.

---

## Environment note — Windows Smart App Control

This machine runs **Smart App Control in enforced mode**. It blocks compiled
extension DLLs (`.pyd`) that have no reputation yet with Microsoft's
Intelligent Security Graph, which means **brand-new releases of numpy, scipy and
scikit-learn fail at import** with:

```
ImportError: DLL load failed while importing _pcg64:
An Application Control policy has blocked this file.
```

The pins in `pyproject.toml` are mature, widely-downloaded builds that load
cleanly. **Do not bump numpy / scipy / scikit-learn / pandas without
re-testing imports on this machine.** If a new pin is blocked, step back to an
older release rather than disabling Smart App Control.

---

## Layout

```
data/raw/          source xlsx (committed — private repo)
data/processed/    parquet artefacts (gitignored)
configs/           *.yaml thresholds and settings
ml/                data loading, features, detectors, models
backend/           FastAPI service
frontend/          React dashboard
models/            trained artefacts (gitignored)
presentation/      SIH pitch material
tests/             pytest
```
