"""Lions-style commercial Excel report from discovery + playlist verify."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from ..schemas import BrandResult, ComplianceRow, DOUBTFUL_STATUSES, VerificationStatus
from .playlist import PlaylistSlot


_HEADER_FONT = Font(bold=True)


def _write_header(sheet, titles: Sequence[str]) -> None:
    sheet.append(list(titles))
    for cell in sheet[1]:
        cell.font = _HEADER_FONT


def _seconds_per_salida(brand: BrandResult) -> float:
    if brand.appearances <= 0:
        return 0.0
    return round(brand.total_seconds / brand.appearances, 2)


def _panel_kind(brand: BrandResult) -> str:
    return brand.panel_kind or ""


def _minuto_label(start_sec: float) -> str:
    minute = int(start_sec) // 60
    second = int(start_sec) % 60
    return f"{minute}.{second:02d}"


def _scheduled_keys(slots: Sequence[PlaylistSlot]) -> set[tuple[str, str, int]]:
    """(period, catalog-ish brand upper, start_sec rounded) for extras filter."""
    keys: set[tuple[str, str, int]] = set()
    for slot in slots:
        if slot.period not in {"1T", "2T"}:
            continue
        keys.add((slot.period, slot.brand.strip().upper(), int(round(slot.start_sec))))
    return keys


def write_commercial_report(
    path: str | Path,
    *,
    led_brands: Sequence[BrandResult],
    fixed_brands: Sequence[BrandResult],
    slots: Sequence[PlaylistSlot],
    compliance: Sequence[ComplianceRow],
    hit_rate: float | None = None,
    analyzed_seconds: int = 0,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()

    resumen = workbook.active
    assert resumen is not None
    resumen.title = "Resumen"
    _write_header(
        resumen,
        ["Cliente", "Minutos", "Salidas", "Seg/salida", "Conteo 1T", "Conteo 2T", "Tipo"],
    )
    by_id = {brand.brand_id: brand for brand in led_brands}
    for brand in led_brands:
        resumen.append(
            [
                brand.name,
                round(brand.total_seconds / 60, 2),
                brand.appearances,
                _seconds_per_salida(brand),
                brand.count_1t,
                brand.count_2t,
                _panel_kind(brand),
            ]
        )
    for brand in fixed_brands:
        led = by_id.get(brand.brand_id)
        if led is not None and led.appearances > 0:
            continue
        if brand.appearances <= 0:
            continue
        resumen.append(
            [
                brand.name,
                round(brand.total_seconds / 60, 2),
                brand.appearances,
                _seconds_per_salida(brand),
                brand.count_1t,
                brand.count_2t,
                brand.panel_kind or "FIJA",
            ]
        )

    salidas = workbook.create_sheet("Salidas")
    _write_header(
        salidas,
        [
            "Cliente",
            "Tipo",
            "Mitad",
            "Reloj inicio",
            "Reloj fin",
            "Duración s",
            "Video inicio s",
            "Zona",
        ],
    )
    for brand in led_brands:
        for segment in brand.segments:
            salidas.append(
                [
                    brand.name,
                    brand.panel_kind or "LED",
                    segment.half,
                    segment.clock_start,
                    segment.clock_end,
                    segment.duration_seconds,
                    segment.video_seconds_start,
                    segment.zone_id or "",
                ]
            )

    cumplimiento = workbook.create_sheet("Cumplimiento")
    _write_header(
        cumplimiento,
        [
            "Cliente",
            "Periodo",
            "Minuto pautado",
            "Pautado s",
            "Duración s",
            "Status",
            "Δ s",
            "Video s",
            "Zona",
            "Captura",
            "Reason",
            "Fuente",
        ],
    )
    rate = hit_rate
    if rate is None:
        decisive = [
            row
            for row in compliance
            if row.status in (VerificationStatus.HIT, VerificationStatus.MISS)
        ]
        rate = (
            sum(1 for row in decisive if row.status == VerificationStatus.HIT)
            / len(decisive)
            if decisive
            else 0.0
        )
    for row in compliance:
        cumplimiento.append(
            [
                row.brand,
                row.period,
                _minuto_label(row.scheduled_start_sec),
                row.scheduled_start_sec,
                row.duration_sec,
                row.status.value if hasattr(row.status, "value") else str(row.status),
                row.delta_sec if row.delta_sec is not None else "",
                row.observed_video_sec if row.observed_video_sec is not None else "",
                row.zone or "",
                row.capture_path or "",
                row.reason or "",
                row.source or "",
            ]
        )
    cumplimiento.append([])
    cumplimiento.append(["Analizado s", analyzed_seconds])
    cumplimiento.append(["Hit rate HIT/(HIT+MISS)", round(rate * 100, 1)])

    dudosas = workbook.create_sheet("Dudosas")
    _write_header(
        dudosas,
        [
            "Cliente",
            "Periodo",
            "Minuto pautado",
            "Status",
            "Δ s",
            "Video s",
            "Zona",
            "Captura",
            "Reason",
        ],
    )
    for row in compliance:
        status = row.status
        if status not in DOUBTFUL_STATUSES:
            continue
        dudosas.append(
            [
                row.brand,
                row.period,
                _minuto_label(row.scheduled_start_sec),
                status.value if hasattr(status, "value") else str(status),
                row.delta_sec if row.delta_sec is not None else "",
                row.observed_video_sec if row.observed_video_sec is not None else "",
                row.zone or "",
                row.capture_path or "",
                row.reason or "",
            ]
        )

    extras = workbook.create_sheet("Extras")
    _write_header(
        extras,
        [
            "Cliente",
            "Tipo",
            "Mitad",
            "Reloj inicio",
            "Reloj fin",
            "Duración s",
            "Video inicio s",
            "Zona",
        ],
    )
    scheduled = _scheduled_keys(slots)
    scheduled_brands = {brand for _, brand, _ in scheduled}
    for brand in list(led_brands) + list(fixed_brands):
        name_upper = brand.name.strip().upper()
        for segment in brand.segments:
            # Extra = discovery segment whose brand is not in the 1T/2T playlist.
            if name_upper in scheduled_brands:
                continue
            extras.append(
                [
                    brand.name,
                    brand.panel_kind or ("FIJA" if brand in fixed_brands else "LED"),
                    segment.half,
                    segment.clock_start,
                    segment.clock_end,
                    segment.duration_seconds,
                    segment.video_seconds_start,
                    segment.zone_id or "",
                ]
            )

    workbook.save(destination)
    workbook.close()
    return destination
