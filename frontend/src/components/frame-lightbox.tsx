"use client";

import { X } from "lucide-react";
import Image from "next/image";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/button";

export function FrameLightbox({
  src,
  label,
  cropSrc,
  fallbackSrc,
  onClose,
}: {
  src: string;
  label: string;
  cropSrc?: string | null;
  fallbackSrc?: string | null;
  onClose: () => void;
}) {
  const [currentSrc, setCurrentSrc] = useState(src);

  useEffect(() => {
    setCurrentSrc(src);
  }, [src]);

  const showingOnlyCrop = Boolean(fallbackSrc && currentSrc === fallbackSrc);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [onClose]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/80 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={`Frame ampliado: ${label}`}
      onClick={onClose}
    >
      <div
        className="relative my-auto w-full max-w-5xl rounded-2xl border border-border bg-card p-3 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between gap-4 px-1">
          <p className="truncate font-mono text-xs text-muted-foreground">{label}</p>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-10 shrink-0"
            onClick={onClose}
            aria-label="Cerrar frame ampliado"
          >
            <X className="size-4" aria-hidden="true" />
          </Button>
        </div>
        <p className="mb-2 px-1 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
          {showingOnlyCrop
            ? "Recorte LED (este análisis no guardó el frame completo)"
            : "Frame completo"}
        </p>
        <Image
          src={currentSrc}
          alt={label}
          width={1280}
          height={720}
          unoptimized
          className="h-auto max-h-[62vh] w-full rounded-xl object-contain bg-black/40"
          style={{ width: "100%", height: "auto" }}
          onError={() => {
            if (fallbackSrc && currentSrc !== fallbackSrc) {
              setCurrentSrc(fallbackSrc);
            }
          }}
        />
        {cropSrc && cropSrc !== currentSrc && !showingOnlyCrop ? (
          <div className="mt-4 border-t border-border/70 pt-3">
            <p className="mb-2 px-1 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              Recorte LED (detalle)
            </p>
            <Image
              src={cropSrc}
              alt={`Recorte LED · ${label}`}
              width={1280}
              height={120}
              unoptimized
              className="h-auto max-h-[16vh] w-full rounded-lg object-contain bg-black/30"
              style={{ width: "100%", height: "auto" }}
            />
          </div>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}
