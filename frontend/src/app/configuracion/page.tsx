"use client";

import { BrandGroupsEditor } from "@/components/brand-groups-editor";
import { StadiumCalibrationSection } from "@/components/stadium-calibration";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function ConfiguracionPage() {
  return (
    <main className="min-h-dvh overflow-x-hidden bg-background">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_15%_0%,oklch(0.32_0.12_145/0.12),transparent_32%),radial-gradient(circle_at_85%_10%,oklch(0.35_0.1_75/0.09),transparent_25%)]" />
      <div className="relative mx-auto flex w-full max-w-3xl flex-col gap-8 px-4 py-8 sm:px-6 lg:px-8">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            Configuración
          </h1>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Grupos de marcas por defecto y perfiles de estadio. El análisis elige
            un grupo y puede apagar marcas solo para ese partido.
          </p>
        </div>

        <Card className="border-border/80 bg-card/80 shadow-xl shadow-black/15 backdrop-blur-xl">
          <CardHeader className="border-b border-border/60 pb-5">
            <CardTitle className="text-lg">Marcas</CardTitle>
            <CardDescription className="mt-1.5">
              El punto verde es el activo por defecto. En el análisis puedes
              desactivar marcas sin cambiar este catálogo.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-6">
            <BrandGroupsEditor />
          </CardContent>
        </Card>

        <Card className="border-border/80 bg-card/80 shadow-xl shadow-black/15 backdrop-blur-xl">
          <CardHeader className="border-b border-border/60 pb-5">
            <CardTitle className="text-lg">Estadios</CardTitle>
            <CardDescription className="mt-1.5">
              Calibra el crop del marcador y el HSV del césped para un estadio nuevo
              o una nueva versión de cámara.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-6">
            <StadiumCalibrationSection onSaved={() => undefined} />
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
