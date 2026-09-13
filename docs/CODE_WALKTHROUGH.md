# Code walkthrough

A guided tour for a reviewer who has fifteen minutes. It follows one work from the
spreadsheet to a reviewer's verdict, then covers the cross-cutting pieces:
scoping, audit, privacy, learning and tests.

```
data/raw/*.xlsx ─► ml/ (pipeline) ─► data/processed/*.parquet, models/metrics.json
                                         │
                                         ▼
                              backend/app/loader.py ─► SQLite or Postgres
                                                              │
                         FastAPI (backend/app) ◄──────────────┘
                              │  JWT, Scope.apply on every query, hash-chained audit
                              ▼
                     frontend/ (React dashboard, citizen view)
```

---

## 1. Loading and cleaning: `ml/data.py`

[ml/data.py](../ml/data.py) reads the eSAKSHI workbook, parses the four date
columns, standardises statuses and flags impossible date orders without dropping
rows. `LEAKY_COLUMNS` names the dataset's own `flag_*`, `anomaly_score` and
`flag_reasons`. [ml/features.py](../ml/features.py) `assert_leak_safe` refuses to
build a feature table containing any of them. `tests/test_ml.py` checks this.

## 2. The pipeline: `ml/pipeline.py`

`python -m ml.train` calls [ml/pipeline.py](../ml/pipeline.py) `run`, which runs
the stages in order and times each one:

| Stage | Module | What it produces |
|---|---|---|
| Holdout reserved first | [ml/holdout.py](../ml/holdout.py) | 27 whole constituencies removed before any fitting |
| Work type | [ml/work_type.py](../ml/work_type.py) | Keyword rules from `configs/ml.yaml`, then GPU sentence-embedding clustering for the rest (56 types) |
| Quantities and expected cost | [ml/quantity.py](../ml/quantity.py), [ml/expected_cost.py](../ml/expected_cost.py) | Out-of-fold XGBoost on type, state, quantity and embedding SVD; a residual z-score becomes the cost channel |
| State-relative cost | [ml/cost_peers.py](../ml/cost_peers.py) | A descriptive comparison, deliberately kept out of the score (see `configs/ml.yaml`) |
| Rules | [ml/rules.py](../ml/rules.py) | The seven rules recomputed from raw columns, plus severe rules |
| Unsupervised anomaly | [ml/detect_anomaly.py](../ml/detect_anomaly.py) | Isolation Forest and ECOD on robust peer-group features |
| Duplicates and splits | [ml/detect_duplicates.py](../ml/detect_duplicates.py) | Weighted pair score over nearest neighbours; split groups by agency, type, timing and combined value |
| Delay model | [ml/train_delay.py](../ml/train_delay.py) | Probability an open work runs past a year, time-split |
| Proxy model | [ml/train_supervised.py](../ml/train_supervised.py) | Learns the rule label; reported with its caveat |
| Fusion and bands | [ml/risk.py](../ml/risk.py) | Soft-OR `fuse`, percentile `band_cutoffs`, `apply_severe_floor`, bilingual reasons |

Evaluation lives in [ml/evaluate.py](../ml/evaluate.py) (planted anomalies,
per-detector queues) and [ml/evaluate_holdout.py](../ml/evaluate_holdout.py). Both
write into `models/metrics.json`, the single source every later number comes from.

Every threshold and weight is in [configs/ml.yaml](../configs/ml.yaml), usually
with a comment recording the measurement that set it.

## 3. Into the application database: `backend/app/loader.py`

[backend/app/loader.py](../backend/app/loader.py) upserts works, alerts,
duplicate pairs and split groups from the parquet outputs. Two details matter:

- **Stable group ids.** `stable_group_id` hashes member work ids, because the
  pipeline renumbers groups each run and a reviewer's alert must not change id.
- **Workflow survives a reload.** `load_alerts` updates scores but keeps
  status, assignee and escalation; alerts no longer produced are retired, not
  deleted.

Models are in [backend/app/models.py](../backend/app/models.py). The six fusion
channels are stored per work (`sig_*`), which is what makes the simulator and
counterfactuals possible without re-running anything.

## 4. The API: `backend/app/main.py` and `routers/`

[backend/app/main.py](../backend/app/main.py) registers every router in a strict
list (a router that fails to import stops the app) and adds a request-id
middleware. Unhandled errors return a reference, never a traceback.

A typical read endpoint, [routers/alerts.py](../backend/app/routers/alerts.py)
`list_alerts`, depends on `context` from [deps.py](../backend/app/deps.py): the
authenticated user, their `Scope`, and a session. The query then passes through
`ctx.scope.apply`.

## 5. Scoping: one function

[backend/app/scoping.py](../backend/app/scoping.py) `Scope.apply` is the only
place rows are restricted:

- Ministry sees everything.
- A state sees rows where `state` matches.
- A district sees rows where `ida` (its office) matches.
- An MP sees rows with their MP code; alerts are matched through their member
  works.

Aggregates in [queries.py](../backend/app/queries.py) start from
`scope.apply(select(Work))`, so a total can never include a row its caller could
not open. Duplicate pairs require both works in scope. Out-of-scope ids answer
404 through `not_found`. `tests/api/conftest.py` builds a synthetic database laid
out so that each rule has something to leak if it is wrong, and
[test_scoping.py](../tests/api/test_scoping.py) checks them.

## 6. Review workflow and the audit chain

[services/alerts.py](../backend/app/services/alerts.py) implements transitions
(allowed moves in `configs/api.yaml`), assignment within scope, comments,
verdicts and escalation. Every state change calls
[audit.py](../backend/app/audit.py) `append`, which hashes
`sha256(prev_hash + canonical JSON of the event)`. `verify` recomputes the chain;
[test_audit_chain.py](../tests/api/test_audit_chain.py) proves that edits,
deletions and re-hashing are detected.

Cases ([routers/cases.py](../backend/app/routers/cases.py)) group alerts, and
[services/reports.py](../backend/app/services/reports.py) renders the PDF briefs
with fpdf2.

## 7. Explaining and tuning a score: `services/fusion.py`

[backend/app/services/fusion.py](../backend/app/services/fusion.py) imports the
pipeline's own `fuse`, `band_cutoffs` and `apply_severe_floor`:

- `rescore` reproduces the stored scores at the configured weights. On the real
  data the largest difference is 0.005, and a test checks agreement.
- `simulate` answers the threshold simulator: bands, queue size, works entering
  and leaving, and where reviewer verdicts would land.
- `counterfactual` removes each channel's contribution and states the data
  condition that would clear it, using templates in
  [configs/reasons.yaml](../configs/reasons.yaml).

## 8. Learning from verdicts: `services/learning.py`

[backend/app/services/learning.py](../backend/app/services/learning.py) builds
labelled examples, then applies Bayesian re-weighting and a logistic re-ranker.
It reports precision on the evaluate partition only.

- **Examples.** Planted synthetic positives come from `ml/planted.py`, in their
  own table and never shown as works. Reviewer and seeded verdicts come from the
  `feedback` table.
- **Bayesian re-weighting.** A Beta posterior on each channel's confirmed rate
  scales its weight, within bounds.
- **Re-ranker.** A logistic regression on the six channels, trained at 50 or more
  labels.
- **Partitions.** Deterministic 70/30 by hash.

[learning_seed.py](../backend/app/learning_seed.py) seeds negatives only from
documented benign rules, and never seeds a real work as confirmed.

## 9. Privacy: `backend/app/redact.py`

With `PRESENTATION_MODE=1`, [redact.py](../backend/app/redact.py):

- replaces MP and vendor names with stable pseudonyms
- treats a Rajya Sabha "constituency" field as a person's name
- masks private names and phone numbers in descriptions (`mask_private_names`)

Serialisers call `redact_record` last, so nothing leaves the server unmasked. The
public router ([routers/public.py](../backend/app/routers/public.py)) never
returns per-work risk; a test walks every key of every public response.

## 10. The dashboard: `frontend/`

- [src/lib/api.ts](../frontend/src/lib/api.ts): fetch with bearer token, timeouts
  and typed errors.
- [src/lib/query.ts](../frontend/src/lib/query.ts): TanStack Query that retries
  network and 5xx failures only.
- [src/lib/format.ts](../frontend/src/lib/format.ts): lakh and crore formatting,
  and amounts in words in English and Hindi, with unit tests.
- [src/components/AppShell.tsx](../frontend/src/components/AppShell.tsx):
  role-filtered navigation ([nav.ts](../frontend/src/components/nav.ts)), the
  Ctrl K palette, and the API-unreachable banner.
- [src/components/common.tsx](../frontend/src/components/common.tsx):
  `QueryState` gives every panel designed loading, error and empty states;
  `ErrorBoundary` catches crashes and stale bundles.
- [src/components/evidence.tsx](../frontend/src/components/evidence.tsx): the
  shared evidence panels (reasons, signals, SHAP bars, peer chart, audit
  timeline, "what would clear this").
- [src/pages/](../frontend/src/pages): one file per screen.
  [RiskMap.tsx](../frontend/src/pages/RiskMap.tsx) joins API rows to district
  boundaries on `map_key` (state and district, with the alias table in
  [configs/district_aliases.yaml](../configs/district_aliases.yaml)).
- [src/locales/](../frontend/src/locales): English and Hindi, kept in step by
  `locales.test.ts`.

## 11. Tests

| Suite | Command | What it guards |
|---|---|---|
| ML and data | `pytest tests/test_*.py` | Data invariants, leakage, holdout exclusion, Phase A detectors, live scoring |
| API | `pytest tests/api` | Scoping, workflow, audit chain, ingest, redaction, simulator, learning, demo seed |
| Frontend unit | `npm --prefix frontend test` | Formatting and words, locale parity |
| End to end | `npm --prefix frontend run e2e` | Four roles on every page with no console errors, scoping, resilience, screenshots |

## 12. Running the demo

[demo.ps1](../demo.ps1) is the verified path: it checks the environment,
builds what is missing, runs [demo_seed.py](../backend/app/demo_seed.py) (which
fails loudly if a scenario is missing), and starts both servers.
[docs/DEMO_SCRIPT.md](DEMO_SCRIPT.md) is the five-minute walkthrough.
