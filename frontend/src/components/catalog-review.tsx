"use client";

import { ArrowUp, Check, FileText, FolderOpen, LoaderCircle, ZoomIn } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { FrameLightbox } from "@/components/frame-lightbox";
import { ModalOverlay } from "@/components/modal-overlay";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  type CatalogFrame,
  type JobCatalog,
  catalogFrameCropUrl,
  catalogFrameImageUrl,
  confirmJobCatalog,
  getFrameUrl,
  getJobCatalog,
  patchCatalogFrame,
  resolveApiUrl,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/** Viewport FAB — portal to body so Card filter/backdrop-blur cannot trap `fixed`. */
function CatalogFabPortal({ children }: { children: ReactNode }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  if (!mounted) return null;
  return createPortal(children, document.body);
}

function frameSrc(jobId: string, frame: CatalogFrame) {
  if (frame.image_url) return resolveApiUrl(frame.image_url);
  return catalogFrameImageUrl(jobId, frame.id);
}

function frameCropSrc(jobId: string, frame: CatalogFrame) {
  if (frame.crop_image_url) return resolveApiUrl(frame.crop_image_url);
  return catalogFrameCropUrl(jobId, frame.id);
}

function lightboxSrc(jobId: string, frame: CatalogFrame) {
  if (frame.has_context) return frameSrc(jobId, frame);
  return getFrameUrl(jobId, frame.half, frame.frame_idx);
}

function openFrameLightbox(
  jobId: string,
  frame: CatalogFrame,
  brandName?: string,
) {
  const catalogImage = frameSrc(jobId, frame);
  return {
    src: lightboxSrc(jobId, frame),
    fallbackSrc: catalogImage,
    cropSrc: frameCropSrc(jobId, frame),
    label: frameLabel(frame, brandName),
  };
}

function frameLabel(frame: CatalogFrame, brandName?: string) {
  const parts = [
    brandName,
    frame.half,
    `frame ${frame.frame_idx}`,
    `${frame.time_seconds.toFixed(1)} s`,
  ].filter(Boolean);
  return parts.join(" · ");
}

function toggleId(list: number[], id: number) {
  return list.includes(id) ? list.filter((item) => item !== id) : [...list, id];
}

function CatalogThumb({
  jobId,
  frame,
  brandName,
  selected,
  selectable,
  size,
  badge,
  onToggle,
  onZoom,
}: {
  jobId: string;
  frame: CatalogFrame;
  brandName?: string;
  selected: boolean;
  selectable: boolean;
  size: "lg" | "md" | "sm";
  badge?: string;
  onToggle: () => void;
  onZoom: () => void;
}) {
  const src = frameSrc(jobId, frame);
  const cropSrc = frameCropSrc(jobId, frame);
  const sizeClass =
    size === "lg"
      ? "aspect-[16/10] w-full"
      : size === "md"
        ? "aspect-video w-full"
        : "aspect-video w-full";
  const showCropStrip = Boolean(frame.has_context && cropSrc && size !== "sm");

  return (
    <div
      className={cn(
        "group/thumb overflow-hidden rounded-xl border bg-card/70",
        selected
          ? "border-[#39ff14] ring-2 ring-[#39ff14]/70 shadow-[0_0_0_1px_#39ff14,0_0_18px_rgba(57,255,20,0.55),0_0_36px_rgba(57,255,20,0.25)]"
          : "border-border/80",
      )}
    >
      <div className="relative bg-muted/30">
        {selectable ? (
          <button
            type="button"
            onClick={onToggle}
            className={cn(
              sizeClass,
              "block w-full text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
            )}
            aria-pressed={selected}
            aria-label={`${selected ? "Quitar selección" : "Seleccionar"} ${frameLabel(frame, brandName)}`}
          >
            <Image
              src={src}
              alt={frameLabel(frame, brandName)}
              width={size === "sm" ? 160 : 320}
              height={size === "sm" ? 90 : 180}
              unoptimized
              className="h-full w-full object-cover"
            />
          </button>
        ) : (
          <div className={sizeClass}>
            <Image
              src={src}
              alt={frameLabel(frame, brandName)}
              width={size === "sm" ? 160 : 320}
              height={size === "sm" ? 90 : 180}
              unoptimized
              className="h-full w-full object-cover"
            />
          </div>
        )}
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className="absolute right-1.5 bottom-1.5 size-8 bg-black/55 text-white opacity-0 hover:bg-black/70 hover:text-white group-hover/thumb:opacity-100 group-focus-within/thumb:opacity-100"
          onClick={onZoom}
          aria-label={`Ampliar ${frameLabel(frame, brandName)}`}
        >
          <ZoomIn className="size-3.5" aria-hidden="true" />
        </Button>
      </div>
      {showCropStrip ? (
        <div className="border-t border-border/60 bg-black/25 px-1.5 py-1">
          <Image
            src={cropSrc!}
            alt={`Recorte LED · ${frameLabel(frame, brandName)}`}
            width={320}
            height={40}
            unoptimized
            className="h-7 w-full object-contain sm:h-8"
          />
        </div>
      ) : null}
      <div className="flex items-center justify-between gap-2 border-t border-border/70 bg-muted/35 px-2 py-2">
        <div className="flex min-w-0 flex-wrap items-center gap-1">
          {badge ? (
            <Badge variant="secondary" className="text-[10px]">
              {badge}
            </Badge>
          ) : null}
          {frame.posicion ? (
            <Badge variant="outline" className="max-w-full truncate text-[10px] text-muted-foreground">
              {frame.posicion}
            </Badge>
          ) : null}
        </div>
        <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
          {frame.half} · {frame.time_seconds.toFixed(0)}s
        </span>
      </div>
    </div>
  );
}

function groupBySimilarity(frames: CatalogFrame[]) {
  const groups: { id: number; frames: CatalogFrame[] }[] = [];
  for (const frame of frames) {
    const groupId = frame.similarity_group ?? groups.length;
    const last = groups[groups.length - 1];
    if (last && last.id === groupId) {
      last.frames.push(frame);
    } else {
      groups.push({ id: groupId, frames: [frame] });
    }
  }
  return groups;
}

export function CatalogReview({
  jobId,
  live = false,
  readOnly = false,
}: {
  jobId: string;
  live?: boolean;
  readOnly?: boolean;
}) {
  const [catalog, setCatalog] = useState<JobCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selectedPositive, setSelectedPositive] = useState<number[]>([]);
  const [selectedAttention, setSelectedAttention] = useState<number[]>([]);
  const [assignBrandId, setAssignBrandId] = useState("");
  const [emptyOpen, setEmptyOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [successOpen, setSuccessOpen] = useState(false);
  const [lightbox, setLightbox] = useState<{
    src: string;
    cropSrc?: string | null;
    fallbackSrc?: string | null;
    label: string;
  } | null>(null);

  const load = useCallback(
    async (resetSelection = false) => {
      const data = await getJobCatalog(jobId);
      setCatalog(data);
      if (resetSelection) {
        setSelectedPositive([]);
        setSelectedAttention([]);
      }
    },
    [jobId],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void load(true)
      .then(() => {
        if (!cancelled) setError(null);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "No se pudo cargar el catálogo.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [load]);

  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => {
      void load(false).catch(() => {
        /* keep last good snapshot while analysis runs */
      });
    }, 2500);
    return () => window.clearInterval(timer);
  }, [live, load]);

  const confirmed = Boolean(
    catalog?.catalog_confirmed_at || catalog?.progress.confirmed,
  );
  const locked = confirmed || readOnly;

  const runPatches = async (ids: number[], patch: Parameters<typeof patchCatalogFrame>[2]) => {
    setBusy(true);
    setError(null);
    try {
      for (const id of ids) {
        await patchCatalogFrame(jobId, id, patch);
      }
      await load(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo actualizar el catálogo.");
    } finally {
      setBusy(false);
    }
  };

  const handleConfirm = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await confirmJobCatalog(jobId);
      setCatalog(next);
      setConfirmOpen(false);
      setSelectedPositive([]);
      setSelectedAttention([]);
      setSuccessOpen(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo confirmar el catálogo.");
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-4" aria-busy="true" aria-label="Cargando catálogo">
        <div className="h-6 w-48 animate-pulse rounded-md bg-muted/50" />
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4">
          {Array.from({ length: 8 }).map((_, index) => (
            <div key={index} className="aspect-video animate-pulse rounded-lg bg-muted/40" />
          ))}
        </div>
      </div>
    );
  }

  if (error && !catalog) {
    return <p className="text-sm text-destructive">{error}</p>;
  }

  if (!catalog) return null;

  const frameCount =
    catalog.progress.positives + catalog.progress.attention + catalog.progress.empty;
  if (live && frameCount === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Los frames van a aparecer aquí apenas el análisis lea la valla LED.
      </p>
    );
  }

  const scrollToId = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div id="catalog-top" className="relative space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold">
            {live ? "Frames detectados (en vivo)" : "Revisión de catálogo"}
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            {catalog.progress.positives} propuestos · {catalog.progress.attention} atención ·{" "}
            {catalog.progress.empty} sin publicidad
            {catalog.discarded_count
              ? ` · ${catalog.discarded_count} descartados`
              : ""}
            {live ? " · revisión completa al terminar" : ""}
          </p>
        </div>
        {confirmed ? (
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="gap-2 border-primary/25 text-primary">
              <Check className="size-3.5" aria-hidden="true" />
              Confirmado
            </Badge>
            <Link href={`/informe?job=${encodeURIComponent(jobId)}`} className={cn(buttonVariants(), "h-10 gap-2")}>
              <FileText className="size-4" aria-hidden="true" />
              Ver informe
            </Link>
          </div>
        ) : !locked ? (
          <Button
            type="button"
            className="h-10"
            onClick={() => setConfirmOpen(true)}
            disabled={busy}
          >
            Confirmar catálogo
          </Button>
        ) : null}
      </div>

      {error ? <p className="text-xs text-destructive">{error}</p> : null}

      <section aria-labelledby="catalog-positives-heading" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 id="catalog-positives-heading" className="text-sm font-semibold">
            Exposición detectada
          </h4>
          {!locked ? (
            <Button
              type="button"
              variant="outline"
              className="h-9"
              disabled={busy || selectedPositive.length === 0}
              onClick={() => void runPatches(selectedPositive, { action: "false_positive" })}
            >
              {busy ? (
                <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
              ) : null}
              Falso positivo
              {selectedPositive.length ? ` (${selectedPositive.length})` : ""}
            </Button>
          ) : null}
        </div>
        {catalog.brands.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border/70 px-4 py-6 text-center text-sm text-muted-foreground">
            Este grupo no tiene propuestos.
          </p>
        ) : (
          catalog.brands.map((brand) => (
            <div
              key={brand.brand_id}
              id={`brand-${brand.brand_id}`}
              className="scroll-mt-4 space-y-3 rounded-xl border border-border/80 bg-card/40 p-4 shadow-sm"
            >
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/60 pb-3">
                <h5 className="text-sm font-semibold text-foreground">{brand.name}</h5>
                <Badge variant="secondary" className="font-mono text-[10px]">
                  {brand.frames.length} frame{brand.frames.length === 1 ? "" : "s"}
                </Badge>
              </div>
              {brand.frames.length === 0 ? (
                <p className="rounded-lg border border-dashed border-border/70 px-3 py-4 text-center text-xs text-muted-foreground">
                  Este grupo no tiene propuestos
                </p>
              ) : (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
                  {brand.frames.map((frame) => (
                    <CatalogThumb
                      key={frame.id}
                      jobId={jobId}
                      frame={frame}
                      brandName={brand.name}
                      selected={selectedPositive.includes(frame.id)}
                      selectable={!locked}
                      size="md"
                      badge="Propuesto"
                      onToggle={() => setSelectedPositive((current) => toggleId(current, frame.id))}
                      onZoom={() => setLightbox(openFrameLightbox(jobId, frame, brand.name))}
                    />
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </section>

      <section
        id="uncatalogued"
        aria-labelledby="catalog-uncatalogued-heading"
        className="scroll-mt-4 space-y-3 rounded-xl border border-border/80 bg-muted/20 p-4"
      >
        <h4 id="catalog-uncatalogued-heading" className="text-sm font-semibold">
          No catalogados
        </h4>
        <Tabs defaultValue="attention" className="w-full">
          <TabsList className="h-auto bg-muted/60 p-1">
            <TabsTrigger value="attention" className="min-h-9 px-3 text-xs">
              Atención ({catalog.attention.length})
            </TabsTrigger>
            <TabsTrigger value="empty" className="min-h-9 px-3 text-xs">
              Sin publicidad ({catalog.empty.length})
            </TabsTrigger>
          </TabsList>
          <TabsContent value="attention" className="mt-3 space-y-3">
            {!locked ? (
              <div className="flex flex-wrap items-center gap-2">
                <Select
                  value={assignBrandId}
                  onValueChange={(value) => {
                    if (value) setAssignBrandId(value);
                  }}
                  disabled={busy || catalog.brands.length === 0}
                >
                  <SelectTrigger className="h-10 min-w-48 bg-background/60">
                    <SelectValue placeholder="Elige una marca" />
                  </SelectTrigger>
                  <SelectContent>
                    {catalog.brands.map((brand) => (
                      <SelectItem key={brand.brand_id} value={brand.brand_id}>
                        {brand.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  type="button"
                  variant="secondary"
                  className="h-10"
                  disabled={
                    busy || selectedAttention.length === 0 || !assignBrandId
                  }
                  onClick={() =>
                    void runPatches(selectedAttention, {
                      action: "assign",
                      brand_id: assignBrandId,
                    })
                  }
                >
                  Asignar
                  {selectedAttention.length ? ` (${selectedAttention.length})` : ""}
                </Button>
              </div>
            ) : null}
            {catalog.attention.length === 0 ? (
              <p className="rounded-lg border border-dashed border-border/70 px-4 py-6 text-sm text-muted-foreground">
                Aquí caen coincidencias débiles y textos OCR que no cerraron con una
                marca. Selecciona recortes y asígnalos si reconoces el sponsor.
              </p>
            ) : (
              <div className="space-y-5">
                <p className="text-xs text-muted-foreground">
                  Ordenados por parecido visual (aprox.). Revisa un grupo a la vez.
                </p>
                {groupBySimilarity(catalog.attention).map((group, index) => (
                  <div key={`att-${group.id}`} className="space-y-2">
                    <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                      Grupo similar {index + 1}
                      <span className="normal-case tracking-normal">
                        {" "}
                        · {group.frames.length} frame{group.frames.length === 1 ? "" : "s"}
                      </span>
                    </p>
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      {group.frames.map((frame) => (
                        <div key={frame.id} className="space-y-1">
                          <CatalogThumb
                            jobId={jobId}
                            frame={frame}
                            selected={selectedAttention.includes(frame.id)}
                            selectable={!locked}
                            size="lg"
                            badge="Atención"
                            onToggle={() =>
                              setSelectedAttention((current) => toggleId(current, frame.id))
                            }
                            onZoom={() => setLightbox(openFrameLightbox(jobId, frame))}
                          />
                          {frame.ocr_text ? (
                            <p className="truncate font-mono text-[10px] text-muted-foreground">
                              {frame.ocr_text}
                            </p>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </TabsContent>
          <TabsContent value="empty" className="mt-3">
            {catalog.empty.length === 0 ? (
              <p className="text-xs text-muted-foreground">No hay recortes vacíos.</p>
            ) : emptyOpen ? (
              <div className="space-y-4">
                <p className="text-xs text-muted-foreground">
                  Agrupados por parecido visual para revisar más rápido.
                </p>
                {groupBySimilarity(catalog.empty).map((group, index) => (
                  <div key={`empty-${group.id}`} className="space-y-2">
                    <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                      Grupo similar {index + 1}
                      <span className="normal-case tracking-normal">
                        {" "}
                        · {group.frames.length}
                      </span>
                    </p>
                    <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6">
                      {group.frames.map((frame) => (
                        <CatalogThumb
                          key={frame.id}
                          jobId={jobId}
                          frame={frame}
                          selected={false}
                          selectable={false}
                          size="sm"
                          onToggle={() => undefined}
                          onZoom={() => setLightbox(openFrameLightbox(jobId, frame))}
                        />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <Button
                type="button"
                variant="outline"
                className="h-9"
                onClick={() => setEmptyOpen(true)}
              >
                Mostrar más ({catalog.empty.length})
              </Button>
            )}
          </TabsContent>
        </Tabs>
      </section>

      <CatalogFabPortal>
        <div
          className="pointer-events-none fixed inset-x-0 bottom-0 z-[90] flex flex-col items-end gap-2 p-4 pb-[max(1rem,env(safe-area-inset-bottom))]"
          aria-label="Acciones rápidas de catálogo"
        >
          {!locked && selectedAttention.length > 0 ? (
            <div className="pointer-events-auto flex max-w-[min(100%,28rem)] flex-wrap items-center justify-end gap-2 rounded-2xl border border-border bg-card/95 p-2 shadow-2xl backdrop-blur-md">
              <Select
                value={assignBrandId}
                onValueChange={(value) => {
                  if (value) setAssignBrandId(value);
                }}
                disabled={busy || catalog.brands.length === 0}
              >
                <SelectTrigger className="h-10 min-w-36 bg-background/80 sm:min-w-44">
                  <SelectValue placeholder="Marca" />
                </SelectTrigger>
                <SelectContent className="z-[110]">
                  {catalog.brands.map((brand) => (
                    <SelectItem key={brand.brand_id} value={brand.brand_id}>
                      {brand.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                type="button"
                className="h-10 cursor-pointer gap-2"
                disabled={busy || !assignBrandId}
                onClick={() =>
                  void runPatches(selectedAttention, {
                    action: "assign",
                    brand_id: assignBrandId,
                  })
                }
              >
                {busy ? (
                  <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Check className="size-4" aria-hidden="true" />
                )}
                Asignar ({selectedAttention.length})
              </Button>
            </div>
          ) : null}
          <div className="pointer-events-auto flex flex-col items-end gap-2">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              className="h-10 cursor-pointer gap-2 shadow-lg"
              onClick={() => scrollToId("catalog-top")}
            >
              <ArrowUp className="size-4" aria-hidden="true" />
              Arriba
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              className="h-10 cursor-pointer gap-2 shadow-lg"
              onClick={() => scrollToId("uncatalogued")}
            >
              <FolderOpen className="size-4" aria-hidden="true" />
              No catalogados
            </Button>
            {!confirmed && !locked ? (
              <Button
                type="button"
                size="sm"
                className="h-10 cursor-pointer gap-2 shadow-lg"
                onClick={() => setConfirmOpen(true)}
                disabled={busy}
              >
                <Check className="size-4" aria-hidden="true" />
                Confirmar catálogo
              </Button>
            ) : null}
          </div>
        </div>
      </CatalogFabPortal>

      <ModalOverlay
        open={confirmOpen}
        onClose={() => {
          if (!busy) setConfirmOpen(false);
        }}
        labelledBy="confirm-catalog-title"
      >
        <h3 id="confirm-catalog-title" className="text-base font-semibold">
          Confirmar catálogo
        </h3>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          Confirmás el catálogo de este partido. El informe usa solo positivos y
          asignaciones; los falsos positivos y lo no asignado quedan fuera.
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button
            type="button"
            variant="ghost"
            onClick={() => setConfirmOpen(false)}
            disabled={busy}
          >
            Cancelar
          </Button>
          <Button type="button" onClick={() => void handleConfirm()} disabled={busy}>
            {busy ? (
              <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
            ) : null}
            Confirmar
          </Button>
        </div>
      </ModalOverlay>

      <ModalOverlay
        open={successOpen}
        onClose={() => setSuccessOpen(false)}
        labelledBy="catalog-success-title"
      >
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
            <Check className="size-5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h3 id="catalog-success-title" className="text-base font-semibold">
              Catálogo confirmado
            </h3>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              El informe ya está listo con las marcas y tiempos de este partido.
            </p>
          </div>
        </div>
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <Button type="button" variant="ghost" onClick={() => setSuccessOpen(false)}>
            Seguir aquí
          </Button>
          <Link
            href={`/informe?job=${encodeURIComponent(jobId)}`}
            className={cn(buttonVariants(), "h-10 gap-2")}
            onClick={() => setSuccessOpen(false)}
          >
            <FileText className="size-4" aria-hidden="true" />
            Ver informe
          </Link>
        </div>
      </ModalOverlay>

      {lightbox ? (
        <FrameLightbox
          src={lightbox.src}
          fallbackSrc={lightbox.fallbackSrc}
          cropSrc={lightbox.cropSrc}
          label={lightbox.label}
          onClose={() => setLightbox(null)}
        />
      ) : null}
    </div>
  );
}
