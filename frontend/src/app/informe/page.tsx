"use client";

import { ArrowLeft, ChevronDown, FileText, LoaderCircle, ZoomIn } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { FrameLightbox } from "@/components/frame-lightbox";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import {
  type JobReport,
  type ReportBrand,
  type ReportFrame,
  type ReportSegment,
  getJobReport,
  resolveApiUrl,
} from "@/lib/api";
import { cn } from "@/lib/utils";

function frameSrc(frame: ReportFrame) {
  return resolveApiUrl(frame.image_url);
}

function frameCropSrc(frame: ReportFrame) {
  if (!frame.crop_image_url) return null;
  return resolveApiUrl(frame.crop_image_url);
}

function SegmentDetail({
  segment,
  brandName,
  onZoom,
}: {
  segment: ReportSegment;
  brandName: string;
  onZoom: (frame: ReportFrame, brandName: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl border border-border/70 bg-background/30">
      <button
        type="button"
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/20"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <ChevronDown
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
          aria-hidden="true"
        />
        <div className="min-w-0 flex-1">
          <p className="font-mono text-sm text-foreground">
            {segment.half} · {segment.clock_start} → {segment.clock_end}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {segment.duration_seconds} s · {segment.frame_count} frame
            {segment.frame_count === 1 ? "" : "s"}
            {segment.posicion ? ` · ${segment.posicion}` : ""}
          </p>
        </div>
        <div className="relative hidden h-12 w-28 overflow-hidden rounded-md border border-border/60 bg-black/30 sm:block">
          <Image
            src={frameSrc(segment.sample_frame)}
            alt=""
            width={112}
            height={48}
            unoptimized
            className="h-full w-full object-cover"
          />
        </div>
      </button>
      {open ? (
        <div className="border-t border-border/60 px-4 py-4">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
            {segment.frames.map((frame) => (
              <button
                key={frame.id}
                type="button"
                className="group relative overflow-hidden rounded-lg border border-border/70 bg-muted/20 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                onClick={() => onZoom(frame, brandName)}
              >
                <div className="aspect-video">
                  <Image
                    src={frameSrc(frame)}
                    alt={`${brandName} ${frame.half} ${frame.time_seconds}s`}
                    width={240}
                    height={135}
                    unoptimized
                    className="h-full w-full object-cover"
                  />
                </div>
                <span className="absolute right-1.5 bottom-1.5 inline-flex size-7 items-center justify-center rounded-md bg-black/55 text-white opacity-0 group-hover:opacity-100">
                  <ZoomIn className="size-3.5" aria-hidden="true" />
                </span>
                <p className="border-t border-border/50 px-2 py-1 font-mono text-[10px] text-muted-foreground">
                  {frame.half} · {frame.time_seconds.toFixed(0)}s
                </p>
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function BrandSection({
  brand,
  onZoom,
}: {
  brand: ReportBrand;
  onZoom: (frame: ReportFrame, brandName: string) => void;
}) {
  return (
    <section className="overflow-hidden rounded-2xl border border-border/80 bg-card/70 shadow-xl shadow-black/10">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border/60 px-5 py-4">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">
            {brand.name}
            {brand.interest ? (
              <Badge className="ml-2 align-middle bg-primary/15 text-[10px] text-primary">
                Interés
              </Badge>
            ) : null}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {brand.appearances}{" "}
            {brand.appearances === 1 ? "aparición" : "apariciones"} · {brand.duration_label}{" "}
            de exposición
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline" className="font-mono text-[10px]">
            1T {brand.count_1t}
          </Badge>
          <Badge variant="outline" className="font-mono text-[10px]">
            2T {brand.count_2t}
          </Badge>
          <Badge className="bg-primary/15 font-mono text-[10px] text-primary">
            {brand.frame_count} frames
          </Badge>
        </div>
      </div>

      <div className="overflow-x-auto px-5 pt-4">
        <table className="w-full min-w-[520px] text-left text-sm">
          <thead>
            <tr className="border-b border-border/60 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              <th className="pb-2 pr-3 font-medium">#</th>
              <th className="pb-2 pr-3 font-medium">Mitad</th>
              <th className="pb-2 pr-3 font-medium">Desde</th>
              <th className="pb-2 pr-3 font-medium">Hasta</th>
              <th className="pb-2 pr-3 font-medium">Duración</th>
              <th className="pb-2 font-medium">Zona</th>
            </tr>
          </thead>
          <tbody>
            {brand.segments.map((segment, index) => (
              <tr
                key={`${segment.half}-${segment.video_seconds_start}-${index}`}
                className="border-b border-border/40"
              >
                <td className="py-2.5 pr-3 font-mono text-xs text-muted-foreground">
                  {index + 1}
                </td>
                <td className="py-2.5 pr-3 font-mono text-xs">{segment.half}</td>
                <td className="py-2.5 pr-3 font-mono text-xs">{segment.clock_start}</td>
                <td className="py-2.5 pr-3 font-mono text-xs">{segment.clock_end}</td>
                <td className="py-2.5 pr-3 font-mono text-xs text-primary">
                  {segment.duration_seconds} s
                </td>
                <td className="py-2.5 text-xs text-muted-foreground">
                  {segment.posicion || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="space-y-2 px-5 py-4">
        <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
          Detalle de salidas
        </p>
        {brand.segments.map((segment, index) => (
          <SegmentDetail
            key={`detail-${segment.half}-${segment.video_seconds_start}-${index}`}
            segment={segment}
            brandName={brand.name}
            onZoom={onZoom}
          />
        ))}
      </div>
    </section>
  );
}

function InformeContent() {
  const searchParams = useSearchParams();
  const jobId = (searchParams.get("job") || "").trim();
  const [report, setReport] = useState<JobReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(jobId));
  const [lightbox, setLightbox] = useState<{
    src: string;
    cropSrc?: string | null;
    fallbackSrc?: string | null;
    label: string;
  } | null>(null);

  useEffect(() => {
    if (!jobId) {
      setLoading(false);
      setError("Falta el id del análisis (?job=...).");
      setReport(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    void getJobReport(jobId)
      .then((data) => {
        if (!cancelled) {
          setReport(data);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "No se pudo cargar el informe.");
          setReport(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  const openFrame = (frame: ReportFrame, brandName: string) => {
    const src = frameSrc(frame);
    setLightbox({
      src,
      fallbackSrc: src,
      cropSrc: frameCropSrc(frame),
      label: `${brandName} · ${frame.half} · frame ${frame.frame_idx} · ${frame.time_seconds.toFixed(1)} s`,
    });
  };

  return (
    <>
      <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
            Informe de exposición
            {jobId ? ` · ${jobId.slice(0, 8)}` : ""}
          </p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">Resultado del partido</h1>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
            Segundos por marca de interés, medidos en intervalos de reloj ya fusionados.
            Los tramos dudosos no entran a ese total: revísalos aparte.
          </p>
        </div>
        <Link href="/" className={cn(buttonVariants({ variant: "outline" }), "h-10 gap-2")}>
          <ArrowLeft className="size-4" aria-hidden="true" />
          Volver al análisis
        </Link>
      </div>

      {loading ? (
        <div className="flex items-center gap-3 rounded-2xl border border-border/70 bg-card/60 px-5 py-8 text-sm text-muted-foreground">
          <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
          Generando informe…
        </div>
      ) : null}

      {error ? (
        <div className="rounded-2xl border border-destructive/40 bg-destructive/10 px-5 py-6">
          <p className="text-sm text-destructive">{error}</p>
          <p className="mt-2 text-xs text-muted-foreground">
            Si todavía no confirmaste el catálogo, vuelve a la revisión y confirma.
          </p>
          <Link
            href="/"
            className={cn(buttonVariants({ variant: "secondary" }), "mt-4 inline-flex h-10")}
          >
            Ir a revisión
          </Link>
        </div>
      ) : null}

      {report ? (
        <div className="space-y-8">
          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-2xl border border-border/70 bg-card/80 p-4 sm:col-span-2">
              <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                Segundos en pantalla · marcas de interés
              </p>
              <p className="mt-2 text-3xl font-semibold tracking-tight text-primary">
                {report.summary.interest_seconds ?? report.summary.total_seconds} s
              </p>
              <p className="mt-2 text-xs text-muted-foreground">
                {report.summary.interest_brand_count ?? report.summary.brand_count} marcas · intervalos
                de reloj fusionados
                {report.stadium_id ? ` · ${report.stadium_id}` : ""}
              </p>
            </div>
            <div className="rounded-2xl border border-border/70 bg-card/80 p-4">
              <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                Apariciones medidas
              </p>
              <p className="mt-2 text-3xl font-semibold tabular-nums">
                {report.summary.appearances}
              </p>
            </div>
            <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4">
              <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-amber-200/80">
                No medible
              </p>
              <p className="mt-2 text-3xl font-semibold tabular-nums text-amber-100">
                {report.summary.doubtful_seconds ?? 0} s
              </p>
              <p className="mt-2 text-xs text-amber-100/70">
                {report.summary.doubtful_count ?? 0} tramos fuera del ±15–20%
              </p>
            </div>
          </section>

          <section className="overflow-hidden rounded-2xl border border-border/80 bg-card/60">
            <div className="flex items-center gap-2 border-b border-border/60 px-5 py-3">
              <FileText className="size-4 text-primary" aria-hidden="true" />
              <h2 className="text-sm font-semibold">Resumen por marca</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-sm">
                <thead>
                  <tr className="border-b border-border/60 bg-muted/20 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                    <th className="px-5 py-3 font-medium">Marca</th>
                    <th className="px-3 py-3 font-medium">Segundos</th>
                    <th className="px-3 py-3 font-medium">Apariciones</th>
                    <th className="px-3 py-3 font-medium">1T</th>
                    <th className="px-3 py-3 font-medium">2T</th>
                    <th className="px-5 py-3 font-medium">Frames</th>
                  </tr>
                </thead>
                <tbody>
                  {report.brands.map((brand) => (
                    <tr key={brand.brand_id} className="border-b border-border/40 last:border-0">
                      <td className="px-5 py-3 font-medium">
                        {brand.name}
                        {brand.interest ? (
                          <span className="ml-2 font-mono text-[10px] uppercase tracking-wide text-primary">
                            interés
                          </span>
                        ) : null}
                      </td>
                      <td className="px-3 py-3 font-mono text-primary">{brand.total_seconds} s</td>
                      <td className="px-3 py-3 font-mono tabular-nums">{brand.appearances}</td>
                      <td className="px-3 py-3 font-mono tabular-nums text-muted-foreground">
                        {brand.count_1t}
                      </td>
                      <td className="px-3 py-3 font-mono tabular-nums text-muted-foreground">
                        {brand.count_2t}
                      </td>
                      <td className="px-5 py-3 font-mono tabular-nums text-muted-foreground">
                        {brand.frame_count}
                      </td>
                    </tr>
                  ))}
                  {report.brands.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-5 py-8 text-sm text-muted-foreground">
                        No hay exposición confirmada para este partido.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </section>

          <section className="overflow-hidden rounded-2xl border border-amber-500/30 bg-amber-500/5">
            <div className="border-b border-amber-500/20 px-5 py-3">
              <h2 className="text-sm font-semibold">Revisión mínima · no medible</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                Estos rangos tienen la valla a la vista pero el OCR no alcanza para medirlos.
                Quedan fuera del margen de ±15–20% y no hace falta revisar el resto del partido.
              </p>
            </div>
            {(report.doubtful_segments ?? []).length === 0 ? (
              <p className="px-5 py-6 text-sm text-muted-foreground">
                No hay tramos dudosos en este informe.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] text-left text-sm">
                  <thead>
                    <tr className="border-b border-amber-500/20 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                      <th className="px-5 py-3 font-medium">Mitad</th>
                      <th className="px-3 py-3 font-medium">Desde</th>
                      <th className="px-3 py-3 font-medium">Hasta</th>
                      <th className="px-3 py-3 font-medium">Segundos</th>
                      <th className="px-5 py-3 font-medium">Motivo</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(report.doubtful_segments ?? []).map((segment) => (
                      <tr
                        key={`${segment.half}-${segment.video_seconds_start}`}
                        className="border-b border-amber-500/10 last:border-0"
                      >
                        <td className="px-5 py-3 font-mono text-xs">{segment.half}</td>
                        <td className="px-3 py-3 font-mono text-xs">{segment.clock_start}</td>
                        <td className="px-3 py-3 font-mono text-xs">{segment.clock_end}</td>
                        <td className="px-3 py-3 font-mono text-xs text-amber-100">
                          {segment.duration_seconds} s
                        </td>
                        <td className="px-5 py-3 text-xs text-muted-foreground">
                          {segment.reason_label}
                          {segment.ocr_text ? ` · ${segment.ocr_text}` : ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <div className="space-y-6">
            {report.brands.map((brand) => (
              <BrandSection key={brand.brand_id} brand={brand} onZoom={openFrame} />
            ))}
          </div>
        </div>
      ) : null}

      {lightbox ? (
        <FrameLightbox
          src={lightbox.src}
          cropSrc={lightbox.cropSrc}
          fallbackSrc={lightbox.fallbackSrc}
          label={lightbox.label}
          onClose={() => setLightbox(null)}
        />
      ) : null}
    </>
  );
}

export default function InformePage() {
  return (
    <main className="mx-auto min-h-[calc(100vh-3.5rem)] w-full max-w-6xl px-4 py-8 sm:px-6">
      <Suspense
        fallback={
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
            Cargando informe…
          </div>
        }
      >
        <InformeContent />
      </Suspense>
    </main>
  );
}
