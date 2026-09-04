"""Lions-style commercial Excel report from discovery + playlist verify."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from ..schemas import BrandResult, ComplianceRow
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

    salidas = workbook.create_sheet("Salidas detectadas")
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

    for title, period in (("Playlist 1T", "1T"), ("Playlist 2T", "2T")):
        sheet = workbook.create_sheet(title)
        _write_header(sheet, ["Cliente", "Minuto", "Duración s", "Inicio s", "Fin s"])
        for slot in slots:
            if slot.period != period:
                continue
            minute = int(slot.start_sec) // 60
            second = int(slot.start_sec) % 60
            sheet.append(
                [
                    slot.brand,
                    f"{minute}.{second:02d}",
                    slot.duration_sec,
                    slot.start_sec,
                    slot.end_sec,
                ]
            )

    cumplimiento = workbook.create_sheet("Cumplimiento")
    _write_header(
        cumplimiento,
        [
            "Cliente",
            "Periodo",
            "Pautado s",
            "Duración s",
            "Visto",
            "% hit",
            "Video s",
            "Fuente",
        ],
    )
    rate = hit_rate if hit_rate is not None else (
        sum(1 for row in compliance if row.hit) / len(compliance) if compliance else 0.0
    )
    for row in compliance:
        cumplimiento.append(
            [
                row.brand,
                row.period,
                row.scheduled_start_sec,
                row.duration_sec,
                "SÍ" if row.hit else "NO",
                round(rate * 100, 1),
                row.observed_video_sec if row.observed_video_sec is not None else "",
                row.source or "",
            ]
        )
    cumplimiento.append([])
    cumplimiento.append(["Analizado s", analyzed_seconds])
    cumplimiento.append(["Hit rate", round(rate * 100, 1)])

    fijas = workbook.create_sheet("Fijas")
    _write_header(fijas, ["Cliente", "Minutos", "Salidas", "Conteo 1T", "Conteo 2T"])
    for brand in fixed_brands:
        if brand.appearances <= 0:
            continue
        fijas.append(
            [
                brand.name,
                round(brand.total_seconds / 60, 2),
                brand.appearances,
                brand.count_1t,
                brand.count_2t,
            ]
        )

    workbook.save(destination)
    workbook.close()
    return destination
