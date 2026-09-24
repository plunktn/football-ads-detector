"""Compare hand-labeled LED minutes with detector segments.

This harness does not score a match by itself. It only prints duration error
on non-doubtful labels and the share of labeled time marked doubtful.

Pass (when a detector file is provided): every brand that has non-doubtful
gold time is within ``--tolerance`` percent (default 20, the wide end of the
±15–20% target). Doubtful labels are excluded from that error and reported
separately. Detector ``doubtful_segments`` (illegible / no medible) are also
excluded from both sides of the error: that time is for review, not for the
±15–20% claim. A segment without ``doubtful`` still counts as clean time.

Examples::

    cd backend
    python eval/gold/compare_gold.py --gold eval/gold/clips/example.json
    python eval/gold/compare_gold.py \\
        --gold eval/gold/clips/mi_clip.json \\
        --detector data/jobs/<id>/result.json \\
        --tolerance 20
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_QUALITIES = {"good", "ok", "bad"}


@dataclass
class BrandScore:
    brand: str
    gold_seconds: float
    detector_seconds: float | None
    error_pct: float | None
    doubtful_pct: float | None


@dataclass
class GoldReport:
    brands: list[BrandScore] = field(default_factory=list)
    doubtful_pct: float | None = None
    tolerance_pct: float = 20.0
    passed: bool | None = None
    detector_unmeasurable_seconds: float = 0.0
    notes: list[str] = field(default_factory=list)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _names(row: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for key in ("brand_id", "brand", "name"):
        text = _text(row.get(key))
        if text:
            found.append(text)
    return found


def _canonical(row: dict[str, Any]) -> str:
    brand_id = _text(row.get("brand_id"))
    if brand_id:
        return brand_id.casefold()
    for key in ("brand", "name"):
        text = _text(row.get(key))
        if text:
            return text.casefold()
    return ""


def _doubtful(row: dict[str, Any]) -> bool:
    value = row.get("doubtful")
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "si", "sí"}
    return bool(value)


def _span_seconds(row: dict[str, Any]) -> float | None:
    if "start_s" in row or "end_s" in row:
        start = row.get("start_s")
        end = row.get("end_s")
    elif "video_seconds_start" in row or "video_seconds_end" in row:
        start = row.get("video_seconds_start")
        end = row.get("video_seconds_end")
    elif "duration_seconds" in row:
        try:
            return max(0.0, float(row["duration_seconds"]))
        except (TypeError, ValueError):
            return None
    else:
        return None
    try:
        start_value = float(start)
        end_value = float(end)
    except (TypeError, ValueError):
        return None
    if end_value < start_value:
        return None
    return end_value - start_value


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def gold_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("labels"), list):
        return [row for row in payload["labels"] if isinstance(row, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("segments"), list):
        return [row for row in payload["segments"] if isinstance(row, dict)]
    raise ValueError("El gold JSON necesita una lista o la clave 'labels'.")


def _timed(row: dict[str, Any]) -> tuple[float, float, str, bool]:
    """Return start, end, half, and whether the times are absolute."""
    half = _text(row.get("half"))
    if "start_s" in row or "end_s" in row or "video_seconds_start" in row or "video_seconds_end" in row:
        if "start_s" in row or "end_s" in row:
            start = float(row.get("start_s"))
            end = float(row.get("end_s"))
        else:
            start = float(row.get("video_seconds_start"))
            end = float(row.get("video_seconds_end"))
        return start, end, half, True
    span = _span_seconds(row) or 0.0
    return 0.0, span, half, False


def _clip_pieces(
    pieces: list[tuple[float, float]],
    cover_start: float,
    cover_end: float,
) -> list[tuple[float, float]]:
    kept: list[tuple[float, float]] = []
    for start, end in pieces:
        if cover_end <= start or cover_start >= end:
            kept.append((start, end))
            continue
        if cover_start > start:
            kept.append((start, cover_start))
        if cover_end < end:
            kept.append((cover_end, end))
    return [(start, end) for start, end in kept if end - start > 1e-9]


def _remaining(
    spans: list[tuple[float, float, str, bool]],
    cuts: list[tuple[float, float, str]],
) -> float:
    total = 0.0
    for start, end, half, absolute in spans:
        if not absolute:
            total += max(0.0, end - start)
            continue
        pieces = [(start, end)]
        for cut_start, cut_end, cut_half in cuts:
            if cut_half and half and cut_half != half:
                continue
            pieces = _clip_pieces(pieces, cut_start, cut_end)
        total += sum(end_piece - start_piece for start_piece, end_piece in pieces)
    return total


def detector_unmeasurable_rows(payload: Any) -> list[dict[str, Any]]:
    """Doubtful / no-medible ranges stored beside LED brands on result.json."""
    if not isinstance(payload, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key in ("doubtful_segments", "unmeasurable"):
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for row in value:
            if not isinstance(row, dict):
                continue
            copied = dict(row)
            copied["doubtful"] = True
            copied["measurable"] = False
            rows.append(copied)
    return rows


def detector_rows(payload: Any) -> list[dict[str, Any]]:
    """Accept a segment list or a job ``result.json`` (LED ``brands`` only)."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        raise ValueError("El JSON del detector no es un objeto ni una lista.")
    if isinstance(payload.get("brands"), list):
        rows: list[dict[str, Any]] = []
        for brand in payload["brands"]:
            if not isinstance(brand, dict):
                continue
            if _text(brand.get("panel_kind")).upper() == "FIJA":
                continue
            for segment in brand.get("segments") or []:
                if not isinstance(segment, dict):
                    continue
                row = dict(segment)
                row.setdefault("brand_id", brand.get("brand_id"))
                row.setdefault("brand", brand.get("name") or brand.get("brand"))
                rows.append(row)
        return rows
    if isinstance(payload.get("segments"), list):
        return [row for row in payload["segments"] if isinstance(row, dict)]
    raise ValueError("El detector necesita 'segments' o 'brands' (result.json LED).")


def compare_minutes(
    labels: list[dict[str, Any]],
    detector: list[dict[str, Any]] | None,
    *,
    tolerance_pct: float = 20.0,
    detector_doubtful: list[dict[str, Any]] | None = None,
) -> GoldReport:
    notes: list[str] = []
    gold_clean: dict[str, list[tuple[float, float, str, bool]]] = {}
    gold_clean_seconds: dict[str, float] = {}
    gold_doubt: dict[str, float] = {}
    display: dict[str, str] = {}
    alias: dict[str, str] = {}

    def bind(row: dict[str, Any]) -> str | None:
        names = _names(row)
        if not names:
            notes.append("Fila sin marca; se omite.")
            return None
        existing = None
        for name in names:
            key = name.casefold()
            if key in alias:
                existing = alias[key]
                break
        canonical = existing or _canonical(row)
        if not canonical:
            notes.append("Fila sin marca; se omite.")
            return None
        display.setdefault(canonical, names[-1] if row.get("brand") or row.get("name") else names[0])
        for name in names:
            alias[name.casefold()] = canonical
        return canonical

    gold_total = 0.0
    gold_doubt_total = 0.0
    for row in labels:
        quality = row.get("quality")
        if quality is not None and _text(quality) not in _QUALITIES:
            notes.append(f"quality desconocida {_text(quality)!r}; se ignora el valor.")
        span = _span_seconds(row)
        if span is None:
            notes.append("Etiqueta sin intervalo válido; se omite.")
            continue
        canonical = bind(row)
        if canonical is None:
            continue
        gold_total += span
        if _doubtful(row):
            gold_doubt[canonical] = gold_doubt.get(canonical, 0.0) + span
            gold_doubt_total += span
        else:
            gold_clean.setdefault(canonical, []).append(_timed(row))
            gold_clean_seconds[canonical] = gold_clean_seconds.get(canonical, 0.0) + span

    cuts: list[tuple[float, float, str]] = []
    unmeasurable_seconds = 0.0
    for row in detector_doubtful or []:
        span = _span_seconds(row)
        if span is None:
            notes.append("Tramo no medible sin intervalo válido; se omite.")
            continue
        start, end, half, absolute = _timed(row)
        unmeasurable_seconds += span
        if absolute:
            cuts.append((start, end, half))
    if unmeasurable_seconds > 0:
        notes.append(
            f"Se excluyeron {unmeasurable_seconds:.1f} s no medibles del detector. "
            f"No entran al error de ±{tolerance_pct:.0f}%."
        )

    detector_clean: dict[str, list[tuple[float, float, str, bool]]] = {}
    if detector is not None:
        for row in detector:
            span = _span_seconds(row)
            if span is None:
                notes.append("Segmento del detector sin intervalo válido; se omite.")
                continue
            canonical = bind(row)
            if canonical is None:
                continue
            if _doubtful(row):
                continue
            detector_clean.setdefault(canonical, []).append(_timed(row))

    keys = sorted(set(gold_clean) | set(gold_doubt) | set(detector_clean), key=lambda item: display.get(item, item))
    brands: list[BrandScore] = []
    comparable = False
    within = True
    for key in keys:
        clean = _remaining(gold_clean.get(key, []), cuts)
        doubt = gold_doubt.get(key, 0.0)
        labeled = gold_clean_seconds.get(key, 0.0) + doubt
        doubtful_pct = (100.0 * doubt / labeled) if labeled > 0 else None
        if detector is None:
            brands.append(
                BrandScore(
                    brand=display.get(key, key),
                    gold_seconds=clean,
                    detector_seconds=None,
                    error_pct=None,
                    doubtful_pct=doubtful_pct,
                )
            )
            continue
        detected = _remaining(detector_clean.get(key, []), cuts)
        if clean > 0:
            error = 100.0 * (detected - clean) / clean
            comparable = True
            if abs(error) > tolerance_pct + 1e-9:
                within = False
        elif detected > 0:
            error = None
            comparable = True
            within = False
            notes.append(
                f"{display.get(key, key)} tiene tiempo de detector y 0 s de gold no dudoso."
            )
        else:
            error = None
        brands.append(
            BrandScore(
                brand=display.get(key, key),
                gold_seconds=clean,
                detector_seconds=detected,
                error_pct=error,
                doubtful_pct=doubtful_pct,
            )
        )

    if detector is None:
        notes.append("Sin salida del detector: el error % queda en n/a. No es una medición.")
        passed = None
    elif not comparable:
        notes.append("No hay tramos no dudosos para comparar.")
        passed = False
    else:
        passed = within

    doubtful_pct = (100.0 * gold_doubt_total / gold_total) if gold_total > 0 else None
    return GoldReport(
        brands=brands,
        doubtful_pct=doubtful_pct,
        tolerance_pct=tolerance_pct,
        passed=passed,
        detector_unmeasurable_seconds=unmeasurable_seconds,
        notes=notes,
    )


def _fmt_seconds(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.1f}%" if value < 0 or value > 0 else "0.0%"


def format_report(report: GoldReport) -> str:
    lines = [
        f"{'marca':<22} {'gold_s':>8} {'det_s':>8} {'error_%':>10} {'dudoso_%':>10}",
    ]
    for brand in report.brands:
        lines.append(
            f"{brand.brand[:22]:<22} "
            f"{brand.gold_seconds:8.1f} "
            f"{_fmt_seconds(brand.detector_seconds):>8} "
            f"{_fmt_pct(brand.error_pct):>10} "
            f"{_fmt_pct(brand.doubtful_pct).replace('+', ''):>10}"
        )
    if report.doubtful_pct is None:
        lines.append("tiempo dudoso: n/a")
    else:
        lines.append(f"tiempo dudoso (etiquetas): {report.doubtful_pct:.1f}%")
    if report.detector_unmeasurable_seconds > 0:
        lines.append(
            "tiempo no medible (detector, excluido): "
            f"{report.detector_unmeasurable_seconds:.1f}s"
        )
    if report.passed is None:
        lines.append("pass: n/a (falta el detector)")
    else:
        status = "PASS" if report.passed else "FAIL"
        lines.append(
            f"pass (±{report.tolerance_pct:.0f}% en tramos no dudosos): {status}"
        )
    for note in report.notes:
        lines.append(f"nota: {note}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compara minutos gold LED contra el detector.")
    parser.add_argument("--gold", required=True, help="JSON de etiquetas (labels).")
    parser.add_argument(
        "--detector",
        default=None,
        help="Segmentos del detector o result.json (solo marcas LED).",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=20.0,
        help="Error absoluto máximo en %% sobre tramos no dudosos (default 20).",
    )
    args = parser.parse_args(argv)
    try:
        labels = gold_rows(load_json(args.gold))
        raw_detector = None if args.detector is None else load_json(args.detector)
        detector = None if raw_detector is None else detector_rows(raw_detector)
        detector_doubtful = (
            [] if raw_detector is None else detector_unmeasurable_rows(raw_detector)
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    report = compare_minutes(
        labels,
        detector,
        tolerance_pct=args.tolerance,
        detector_doubtful=detector_doubtful,
    )
    print(format_report(report))
    if report.passed is None:
        return 0
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
