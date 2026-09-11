"use client";

import { ChevronDown, LoaderCircle, SlidersHorizontal, UploadCloud } from "lucide-react";
import { type ChangeEvent, useState } from "react";

import { proposeCalibration, saveCalibration } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const CALIBRATION_ACCEPT = ".jpg,.jpeg,.png,.bmp,.webp,.mp4,.mov,.mkv,.webm";

export function StadiumCalibrationSection({
  onSaved,
}: {
  onSaved: (stadiumId: string) => void;
}) {
  const [sampleFile, setSampleFile] = useState<File>();
  const [stadiumId, setCalibStadiumId] = useState("");
  const [nombre, setNombre] = useState("");
  const [pais, setPais] = useState("");
  const [cameraJson, setCameraJson] = useState("");
  const [previews, setPreviews] = useState<{
    scoreboard?: string;
    grass?: string;
  }>({});
  const [busy, setBusy] = useState<"propose" | "save" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSample = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setSampleFile(file);
    setError(null);
    setMessage(null);
  };

  const handlePropose = async () => {
    if (!sampleFile) {
      setError("Sube una imagen o un video de muestra.");
      return;
    }
    setBusy("propose");
    setError(null);
    setMessage(null);
    try {
      const proposal = await proposeCalibration(sampleFile);
      setCameraJson(JSON.stringify(proposal.camera, null, 2));
      setPreviews({
        scoreboard: proposal.previews?.scoreboard_jpeg_b64
          ? `data:image/jpeg;base64,${proposal.previews.scoreboard_jpeg_b64}`
          : undefined,
        grass: proposal.previews?.grass_mask_jpeg_b64
          ? `data:image/jpeg;base64,${proposal.previews.grass_mask_jpeg_b64}`
          : undefined,
      });
      setMessage("Propuesta lista. Revisa el crop HSV y guarda el perfil.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo proponer.");
    } finally {
      setBusy(null);
    }
  };

  const handleSave = async () => {
    if (!stadiumId.trim() || !nombre.trim()) {
      setError("Indica el id y el nombre del estadio.");
      return;
    }
    let camera;
    try {
      camera = JSON.parse(cameraJson);
    } catch {
      setError("El JSON de la cámara no es válido.");
      return;
    }
    setBusy("save");
    setError(null);
    setMessage(null);
    try {
      const saved = await saveCalibration({
        stadium_id: stadiumId.trim(),
        nombre: nombre.trim(),
        pais: pais.trim() || null,
        camera,
      });
      setMessage(
        `Perfil ${saved.id} guardado (versión ${saved.version}). Ya aparece en el selector.`,
      );
      onSaved(saved.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <details className="rounded-xl border border-border/70 bg-background/35">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-3 text-sm font-medium text-foreground [&::-webkit-details-marker]:hidden">
        <SlidersHorizontal className="size-4 text-primary" aria-hidden="true" />
        Calibrar estadio
        <ChevronDown className="ml-auto size-4 text-muted-foreground" aria-hidden="true" />
      </summary>
      <div className="space-y-3 border-t border-border/60 px-3 py-3">
        <p className="text-xs text-muted-foreground">
          Sube un frame o un clip corto. El sistema propone crop del marcador y
          HSV del césped; tú confirmas y guardas una nueva versión del perfil.
        </p>
        <label className="flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-border/80 bg-background/40 px-3 py-4 text-center hover:border-primary/60">
          <input
            type="file"
            accept={CALIBRATION_ACCEPT}
            onChange={handleSample}
            className="sr-only"
          />
          <UploadCloud className="mb-2 size-4 text-muted-foreground" aria-hidden="true" />
          <span className="text-xs font-medium text-foreground">
            {sampleFile ? sampleFile.name : "Subir imagen o video de muestra"}
          </span>
        </label>
        <Button
          type="button"
          variant="secondary"
          className="h-10 w-full gap-2"
          onClick={() => void handlePropose()}
          disabled={busy !== null || !sampleFile}
        >
          {busy === "propose" ? (
            <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
          ) : null}
          Proponer
        </Button>
        {(previews.scoreboard || previews.grass) && (
          <div className="grid grid-cols-2 gap-2">
            {previews.scoreboard ? (
              <figure>
                <img
                  src={previews.scoreboard}
                  alt="Recorte propuesto del marcador"
                  className="h-20 w-full rounded-lg border border-border/70 object-cover"
                />
                <figcaption className="mt-1 font-mono text-[10px] text-muted-foreground">
                  Marcador
                </figcaption>
              </figure>
            ) : null}
            {previews.grass ? (
              <figure>
                <img
                  src={previews.grass}
                  alt="Máscara HSV del césped"
                  className="h-20 w-full rounded-lg border border-border/70 object-cover"
                />
                <figcaption className="mt-1 font-mono text-[10px] text-muted-foreground">
                  Césped
                </figcaption>
              </figure>
            ) : null}
          </div>
        )}
        <div className="grid gap-2">
          <div>
            <Label htmlFor="calib-stadium-id" className="text-xs">
              Id del estadio
            </Label>
            <Input
              id="calib-stadium-id"
              value={stadiumId}
              onChange={(event) => setCalibStadiumId(event.target.value)}
              placeholder="capwell"
              className="mt-1 h-10 font-mono text-sm"
            />
          </div>
          <div>
            <Label htmlFor="calib-nombre" className="text-xs">
              Nombre
            </Label>
            <Input
              id="calib-nombre"
              value={nombre}
              onChange={(event) => setNombre(event.target.value)}
              placeholder="Estadio Capwell"
              className="mt-1 h-10 text-sm"
            />
          </div>
          <div>
            <Label htmlFor="calib-pais" className="text-xs">
              País (opcional)
            </Label>
            <Input
              id="calib-pais"
              value={pais}
              onChange={(event) => setPais(event.target.value)}
              placeholder="Ecuador"
              className="mt-1 h-10 text-sm"
            />
          </div>
          <div>
            <Label htmlFor="calib-camera-json" className="text-xs">
              Perfil de cámara (JSON editable)
            </Label>
            <textarea
              id="calib-camera-json"
              value={cameraJson}
              onChange={(event) => setCameraJson(event.target.value)}
              spellCheck={false}
              rows={10}
              className="mt-1 w-full rounded-md border border-input bg-background/60 p-2 font-mono text-[11px] text-foreground"
              placeholder='Pulsa "Proponer" para rellenar crop, HSV y banda LED.'
            />
          </div>
        </div>
        <Button
          type="button"
          className="h-10 w-full"
          onClick={() => void handleSave()}
          disabled={busy !== null || !cameraJson.trim()}
        >
          {busy === "save" ? (
            <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
          ) : null}
          Guardar perfil
        </Button>
        {error ? <p className="text-xs text-destructive">{error}</p> : null}
        {message ? <p className="text-xs text-muted-foreground">{message}</p> : null}
      </div>
    </details>
  );
}
