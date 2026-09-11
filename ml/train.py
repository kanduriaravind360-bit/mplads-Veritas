"""One command that runs the whole pipeline.

    python -m ml.train

Builds work types, features, all four detectors, the risk score, the alert
queue and the roll-ups, then runs the injection test and writes
``models/metrics.json``. Prints per-stage timings and a summary table.
"""

from __future__ import annotations

import argparse
from typing import Any

import pandas as pd

from ml.config import load_config
from ml.evaluate import run_injection_test, write_metrics
from ml.gpu import device_name, torch_device
from ml.pipeline import run


def _print_table(title: str, frame: pd.DataFrame) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    print(frame.to_string(index=False))


def _summary(metrics: dict[str, Any]) -> pd.DataFrame:
    """The short summary table printed at the end of a run."""
    rows: list[dict[str, Any]] = []
    bands = metrics.get("risk_bands", {})
    total = sum(bands.values()) or 1
    for band in ("Low", "Medium", "High", "Critical"):
        n = bands.get(band, 0)
        rows.append({"metric": f"band: {band}", "value": f"{n:,}", "share": f"{n / total:.1%}"})

    dup = metrics.get("duplicates", {})
    spl = metrics.get("split_works", {})
    rows += [
        {"metric": "duplicate clusters", "value": f"{dup.get('clusters', 0):,}", "share": ""},
        {"metric": "works in duplicates", "value": f"{dup.get('works_flagged', 0):,}", "share": ""},
        {"metric": "split-work groups", "value": f"{spl.get('groups', 0):,}", "share": ""},
        {"metric": "works in splits", "value": f"{spl.get('works', 0):,}", "share": ""},
        {
            "metric": "alerts",
            "value": f"{metrics.get('alerts', {}).get('total', 0):,}",
            "share": "",
        },
    ]

    delay = metrics.get("delay_model", {})
    if delay.get("roc_auc") is not None:
        rows.append({"metric": "delay ROC-AUC", "value": f"{delay['roc_auc']:.3f}", "share": ""})
        rows.append({"metric": "delay PR-AUC", "value": f"{delay['pr_auc']:.3f}", "share": ""})

    sup = metrics.get("supervised_model", {})
    if sup:
        rows.append(
            {"metric": "proxy PR-AUC (OOF)", "value": f"{sup['pr_auc_oof']:.3f}", "share": ""}
        )
        rows.append(
            {"metric": "proxy ROC-AUC (OOF)", "value": f"{sup['roc_auc_oof']:.3f}", "share": ""}
        )

    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the MPLADS Sentinel ML pipeline.")
    parser.add_argument("--config", default="ml", help="config name under configs/")
    parser.add_argument(
        "--skip-injection",
        action="store_true",
        help="skip the synthetic injection test (roughly halves runtime)",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    print(f"MPLADS Sentinel - ML pipeline\ndevice: {torch_device()} ({device_name()})\n")

    print("main run:")
    result = run(cfg, save=True)

    injection: dict[str, Any] | None = None
    if not args.skip_injection:
        print("\ninjection test (re-runs detectors on planted anomalies):")
        injection = run_injection_test(cfg)

    path = write_metrics(result.metrics, injection, result.feature_names, cfg)

    counts = pd.DataFrame(result.metrics["work_type"]["counts"]).head(10)
    _print_table("Top 10 work types", counts)
    _print_table("Summary", _summary(result.metrics))

    if injection:
        rows = [
            {
                "injection": kind,
                "n": int(vals["n_injected"]),
                "recall@1%": f"{vals.get('recall_at_top_1pct', 0):.1%}",
                "recall@5%": f"{vals.get('recall_at_top_5pct', 0):.1%}",
            }
            for kind, vals in sorted(injection["per_type"].items())
        ]
        _print_table("Injection test: rank-based recall", pd.DataFrame(rows))

        comp = injection.get("recall_at_top_5pct_before_after", {})
        if comp:
            _print_table(
                "Injection recall at top 5%: before vs after",
                pd.DataFrame(
                    [
                        {
                            "injection": k,
                            "before": f"{v['before_step2b']:.1%}" if v["before_step2b"] else "-",
                            "after": f"{v['after_step2b']:.1%}",
                            "target": f"{v['target']:.0%}" if v["target"] else "-",
                            "met": "yes" if v["target_met"] else "no",
                        }
                        for k, v in sorted(comp.items())
                    ]
                ),
            )

        det = injection.get("detector_recall", {})
        if det:
            _print_table(
                "Injection test: did the intended detector fire",
                pd.DataFrame(
                    [{"injection": k, "detector_fired": f"{v:.1%}"} for k, v in sorted(det.items())]
                ),
            )

    timings = result.metrics["timings_seconds"]
    print(f"\nstage timings (s): {timings}")
    print(f"total: {result.metrics['total_seconds']:.1f}s")
    print(f"metrics written to {path}")
    print(
        "\nNote: outputs are risk indicators for human review, not findings of "
        "fraud. The proxy-label model reproduces a hand-written rule set; see the "
        "CAVEAT in metrics.json."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
