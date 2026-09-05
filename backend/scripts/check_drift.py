#!/usr/bin/env python3
"""Alert when stadium eval precision drifts >5pp vs last calibration baseline.

Usage (repo root):

    python backend/scripts/check_drift.py \\
        --dataset data/eval/ligaecuabet \\
        --baseline data/eval/ligaecuabet/baseline.json \\
        --threshold 0.05

Compares current eval run to a stored baseline (or calibration_runs if present).
Exit code 1 if any brand precision or recall drops by more than threshold.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from eval_pipeline import (  # noqa: E402
    evaluate_dataset,
    load_dataset,
    write_baseline,
)


def _load_baseline(path: Path) -> dict[str, dict[str, float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    brands = payload.get("brands") or {}
    return {str(k): dict(v) for k, v in brands.items()}


def compare_drift(
    current: dict[str, dict[str, float]],
    previous: dict[str, dict[str, float]],
    *,
    threshold: float,
) -> list[str]:
    alerts: list[str] = []
    marcas = sorted(set(current) | set(previous))
    for marca in marcas:
        cur = current.get(marca, {})
        prev = previous.get(marca, {})
        for metric in ("precision", "recall"):
            c = float(cur.get(metric, 0.0))
            p = float(prev.get(metric, 0.0))
            drop = p - c
            if drop > threshold + 1e-12:
                alerts.append(
                    f"{marca}: {metric} dropped {drop:.4f} "
                    f"(prev={p:.4f} cur={c:.4f} threshold={threshold:.4f})"
                )
    return alerts


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check eval metric drift.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--baseline", help="Previous baseline.json path")
    parser.add_argument("--threshold", type=float, default=0.05)
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Use empty predictions (scaffold without clips).",
    )
    parser.add_argument(
        "--write-current",
        help="Optional path to write current metrics JSON.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dataset_path = Path(args.dataset)
    if not dataset_path.is_absolute():
        dataset_path = REPO_ROOT / dataset_path

    baseline_path = (
        Path(args.baseline).resolve()
        if args.baseline
        else dataset_path / "baseline.json"
    )
    if not baseline_path.is_file():
        print(f"Baseline not found: {baseline_path}", file=sys.stderr)
        return 2

    dataset = load_dataset(dataset_path)
    current, meta = evaluate_dataset(
        dataset,
        skip_missing_clips=True,
        synthetic=args.synthetic or not any(
            (dataset_path / ann.clip).is_file() for ann in dataset.annotations
        ),
    )
    previous = _load_baseline(baseline_path)

    if args.write_current:
        write_baseline(
            Path(args.write_current),
            {
                "brands": {
                    m: {k: round(v, 4) for k, v in sorted(metrics.items())}
                    for m, metrics in sorted(current.items())
                },
                "meta": meta,
            },
        )

    alerts = compare_drift(current, previous, threshold=args.threshold)
    if not alerts:
        print(f"OK: no drift above {args.threshold:.2%} vs {baseline_path}")
        return 0

    print("DRIFT ALERTS:")
    for line in alerts:
        print(f"  - {line}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
