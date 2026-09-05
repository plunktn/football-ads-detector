#!/usr/bin/env python3
"""Evaluate the analysis pipeline against annotated ground-truth clips.

Run from the repository root:

    python backend/scripts/eval_pipeline.py --dataset data/eval/ligaecuabet

When no video clips are present (scaffolding / Fase 0 verify), the script still
writes a reproducible ``baseline.json`` with all-zero predictions. Two identical
runs must produce identical baseline files.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.eval.metrics import (  # noqa: E402
    Interval,
    aggregate_brand_totals,
    compute_brand_metrics,
    round_metrics,
)
from app.schemas import BrandInput, Kickoff  # noqa: E402


@dataclass
class Annotation:
    clip: str
    marca: str
    start_s: float
    end_s: float
    brand_id: str | None = None
    zone: str | None = None


@dataclass
class EvalDataset:
    root: Path
    annotations: list[Annotation] = field(default_factory=list)
    brands: list[BrandInput] = field(default_factory=list)


def _parse_annotation(raw: dict[str, Any]) -> Annotation:
    clip = raw.get("clip")
    marca = raw.get("marca")
    if not clip or not marca:
        raise ValueError(f"Annotation missing clip or marca: {raw!r}")
    start_s = float(raw["start_s"])
    end_s = float(raw["end_s"])
    if end_s < start_s:
        raise ValueError(f"Annotation end_s < start_s: {raw!r}")
    return Annotation(
        clip=str(clip),
        marca=str(marca).strip(),
        start_s=start_s,
        end_s=end_s,
        brand_id=raw.get("brand_id"),
        zone=raw.get("zone"),
    )


def _load_json_list(path: Path) -> list[Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON list")
    return payload


def load_dataset(dataset_path: Path) -> EvalDataset:
    """Load annotations and optional brand config from a dataset directory."""
    root = dataset_path.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Dataset directory not found: {root}")

    annotations: list[Annotation] = []
    annotations_file = root / "annotations.json"
    if annotations_file.is_file():
        annotations.extend(
            _parse_annotation(item) for item in _load_json_list(annotations_file)
        )

    for path in sorted(root.glob("*.annotations.json")):
        if path.name == "annotations.json":
            continue
        annotations.extend(_parse_annotation(item) for item in _load_json_list(path))

    if not annotations:
        raise ValueError(
            f"No annotations found in {root}. Expected annotations.json "
            "or *.annotations.json files."
        )

    brands: list[BrandInput] = []
    brands_file = root / "brands.json"
    if brands_file.is_file():
        for item in _load_json_list(brands_file):
            brands.append(
                BrandInput(
                    id=item.get("id"),
                    name=item["name"],
                    aliases=item.get("aliases") or [],
                )
            )

    if not brands:
        seen: dict[str, BrandInput] = {}
        for ann in annotations:
            key = ann.brand_id or ann.marca
            if key not in seen:
                seen[key] = BrandInput(
                    id=ann.brand_id,
                    name=ann.marca,
                    aliases=[],
                )
        brands = list(seen.values())

    return EvalDataset(root=root, annotations=annotations, brands=brands)


def _brand_lookup(brands: list[BrandInput]) -> dict[str, str]:
    """Map pipeline brand_id and normalized name -> display marca."""
    lookup: dict[str, str] = {}
    for brand in brands:
        lookup[brand.id or brand.name] = brand.name
        lookup[brand.name.strip().lower()] = brand.name
    return lookup


def _resolve_marca(
    brand_id: str,
    brand_name: str,
    lookup: dict[str, str],
) -> str:
    if brand_id in lookup:
        return lookup[brand_id]
    key = brand_name.strip().lower()
    if key in lookup:
        return lookup[key]
    return brand_name


def _clip_annotations_by_name(
    annotations: list[Annotation],
) -> dict[str, list[Annotation]]:
    grouped: dict[str, list[Annotation]] = defaultdict(list)
    for ann in annotations:
        grouped[ann.clip].append(ann)
    return grouped


def _gt_intervals_for_clip(
    clip_annotations: list[Annotation],
) -> dict[str, list[Interval]]:
    by_marca: dict[str, list[Interval]] = defaultdict(list)
    for ann in clip_annotations:
        by_marca[ann.marca].append(Interval(ann.start_s, ann.end_s))
    return by_marca


def _predicted_intervals_for_clip(
    analysis_brands: list,
    lookup: dict[str, str],
) -> dict[str, list[Interval]]:
    by_marca: dict[str, list[Interval]] = defaultdict(list)
    for brand in analysis_brands:
        marca = _resolve_marca(brand.brand_id, brand.name, lookup)
        for segment in brand.segments:
            by_marca[marca].append(
                Interval(segment.video_seconds_start, segment.video_seconds_end)
            )
    return by_marca


def _resolve_clip_path(dataset_root: Path, clip_name: str) -> Path:
    candidate = dataset_root / clip_name
    if candidate.is_file():
        return candidate
    for subdir in ("clips", "videos"):
        nested = dataset_root / subdir / clip_name
        if nested.is_file():
            return nested
    return candidate


def _empty_metrics() -> dict[str, float]:
    return {
        "true_positive_seconds": 0.0,
        "predicted_seconds": 0.0,
        "gt_seconds": 0.0,
        "precision": 0.0,
        "recall": 0.0,
        "error_s": 0.0,
    }


def evaluate_dataset(
    dataset: EvalDataset,
    *,
    skip_missing_clips: bool = False,
    synthetic: bool = False,
) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    """Run pipeline (or synthetic empty predictions) and compute per-brand metrics."""
    lookup = _brand_lookup(dataset.brands)
    clips = _clip_annotations_by_name(dataset.annotations)
    all_marcas = sorted({ann.marca for ann in dataset.annotations})

    per_brand_clip_metrics: dict[str, list[dict[str, float]]] = {
        marca: [] for marca in all_marcas
    }
    clips_evaluated: list[str] = []
    clips_missing: list[str] = []
    run_warnings: list[str] = []

    available_clips: dict[str, Path] = {}
    for clip_name in sorted(clips):
        clip_path = _resolve_clip_path(dataset.root, clip_name)
        if clip_path.is_file():
            available_clips[clip_name] = clip_path
        else:
            clips_missing.append(clip_name)

    if (
        clips_missing
        and available_clips
        and not skip_missing_clips
        and not synthetic
    ):
        missing = ", ".join(clips_missing)
        raise FileNotFoundError(
            f"Missing video clip(s) in {dataset.root}: {missing}. "
            "Use --skip-missing-clips to evaluate only available clips, "
            "or --synthetic for a zero-prediction scaffold run."
        )

    if not available_clips:
        run_warnings.append(
            "No video clips found; writing all-zero baseline from ground truth only."
        )

    debug_dir = Path(tempfile.mkdtemp(prefix="eval_pipeline_debug_"))

    for clip_name in sorted(clips):
        gt_by_marca = _gt_intervals_for_clip(clips[clip_name])
        predicted_by_marca: dict[str, list[Interval]] = defaultdict(list)

        clip_path = available_clips.get(clip_name)
        if clip_path is not None and not synthetic:
            from app.pipeline.run import run_analysis

            result = run_analysis(
                [clip_path],
                mode="single",
                duration_mode="full",
                kickoff=Kickoff(first_half_video_seconds=0.0),
                brands=dataset.brands,
                debug_dir=debug_dir,
            )
            predicted_by_marca = _predicted_intervals_for_clip(
                result.brands,
                lookup,
            )
            clips_evaluated.append(clip_name)
        elif clip_path is not None and synthetic:
            clips_evaluated.append(clip_name)

        clip_marcas = sorted(set(gt_by_marca) | set(predicted_by_marca))
        for marca in clip_marcas:
            metrics = compute_brand_metrics(
                predicted_by_marca.get(marca, []),
                gt_by_marca.get(marca, []),
            )
            per_brand_clip_metrics.setdefault(marca, []).append(metrics)

    brand_metrics: dict[str, dict[str, float]] = {}
    for marca in all_marcas:
        clip_metrics = per_brand_clip_metrics.get(marca, [])
        if clip_metrics:
            brand_metrics[marca] = aggregate_brand_totals(clip_metrics)
        else:
            brand_metrics[marca] = _empty_metrics()

    meta = {
        "dataset": str(dataset.root),
        "clips_evaluated": sorted(clips_evaluated),
        "clips_missing": sorted(clips_missing),
        "clips_skipped": sorted(set(clips_missing) - set(clips_evaluated)),
        "synthetic": synthetic,
        "warnings": run_warnings,
    }
    return brand_metrics, meta


def _print_table(brand_metrics: dict[str, dict[str, float]]) -> None:
    header = f"{'marca':<24} | {'precision':>9} | {'recall':>9} | {'error_s':>9}"
    print(header)
    print("-" * len(header))
    for marca in sorted(brand_metrics):
        metrics = brand_metrics[marca]
        print(
            f"{marca:<24} | "
            f"{metrics['precision']:9.4f} | "
            f"{metrics['recall']:9.4f} | "
            f"{metrics['error_s']:9.4f}"
        )


def _baseline_payload(
    brand_metrics: dict[str, dict[str, float]],
    meta: dict[str, Any],
) -> dict[str, Any]:
    brands = {
        marca: round_metrics(metrics)
        for marca, metrics in sorted(brand_metrics.items())
    }
    payload: dict[str, Any] = {
        "brands": brands,
        "clips_evaluated": meta["clips_evaluated"],
        "clips_missing": meta["clips_missing"],
        "clips_skipped": meta["clips_skipped"],
        "synthetic": meta["synthetic"],
    }
    if meta["warnings"]:
        payload["warnings"] = meta["warnings"]
    return payload


def write_baseline(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate pipeline precision/recall against annotated clips.",
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to dataset directory (relative to repo root or absolute).",
    )
    parser.add_argument(
        "--output",
        help="Path for baseline.json (default: <dataset>/baseline.json).",
    )
    parser.add_argument(
        "--skip-missing-clips",
        action="store_true",
        help="Evaluate only clips whose video files exist; still write baseline.",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Skip pipeline inference; use empty predictions (scaffolding).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dataset_path = Path(args.dataset)
    if not dataset_path.is_absolute():
        dataset_path = REPO_ROOT / dataset_path

    dataset = load_dataset(dataset_path)
    brand_metrics, meta = evaluate_dataset(
        dataset,
        skip_missing_clips=args.skip_missing_clips,
        synthetic=args.synthetic,
    )

    for message in meta["warnings"]:
        warnings.warn(message)

    _print_table(brand_metrics)

    output_path = (
        Path(args.output).resolve()
        if args.output
        else dataset_path / "baseline.json"
    )
    payload = _baseline_payload(brand_metrics, meta)
    write_baseline(output_path, payload)
    print(f"\nWrote baseline: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
