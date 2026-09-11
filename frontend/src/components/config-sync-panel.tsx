"use client";

import { CloudDownload, CloudUpload, LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  getSyncStatus,
  syncPull,
  syncPush,
  type SyncStatus,
} from "@/lib/api";

export function ConfigSyncPanel({ onSynced }: { onSynced?: () => void }) {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [busy, setBusy] = useState<"pull" | "push" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const next = await getSyncStatus();
      setStatus(next);
    } catch {
      setStatus(null);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const run = async (mode: "pull" | "push") => {
    setBusy(mode);
    setError(null);
    setMessage(null);
    try {
      if (mode === "pull") {
        const result = await syncPull();
        setMessage(
          `Bajado de cloud: ${result.counts?.brands ?? 0} marcas, ${result.counts?.brand_refs ?? 0} refs.`,
        );
      } else {
        await syncPush();
        setMessage("Subido a cloud. Prod y otros locales ya pueden bajar estos cambios.");
      }
      onSynced?.();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sync falló.");
    } finally {
      setBusy(null);
    }
  };

  const cloudReady = Boolean(status?.cloud_configured);

  return (
    <div className="rounded-xl border border-border/80 bg-muted/20 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-medium text-foreground">Sync con cloud</p>
          <p className="text-xs leading-5 text-muted-foreground">
            Cloud (Railway) es la fuente de verdad de marcas, refs y estadios. El
            video del partido sigue solo en esta máquina.
          </p>
          <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
            {cloudReady
              ? "CLOUD_API_URL + SYNC_TOKEN listos"
              : "Sin CLOUD_API_URL — solo DB local"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="secondary"
            className="h-9 gap-2"
            disabled={!cloudReady || busy !== null}
            onClick={() => void run("pull")}
          >
            {busy === "pull" ? (
              <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
            ) : (
              <CloudDownload className="size-4" aria-hidden="true" />
            )}
            Bajar de cloud
          </Button>
          <Button
            type="button"
            className="h-9 gap-2"
            disabled={!cloudReady || busy !== null}
            onClick={() => void run("push")}
          >
            {busy === "push" ? (
              <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
            ) : (
              <CloudUpload className="size-4" aria-hidden="true" />
            )}
            Subir a cloud
          </Button>
        </div>
      </div>
      {message ? (
        <p className="mt-3 text-xs text-primary">{message}</p>
      ) : null}
      {error ? (
        <p className="mt-3 text-xs text-destructive">{error}</p>
      ) : null}
    </div>
  );
}
