"use client";

import { ChevronDown, LoaderCircle, Plus, Trash2, UploadCloud } from "lucide-react";
import { useEffect, useState } from "react";

import {
  type BrandGroup,
  createBrand,
  createBrandGroup,
  deleteBrand,
  deleteBrandGroup,
  listBrandGroups,
  patchBrand,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

function brandAliases(name: string): string[] {
  return [name.replace(/\s+/g, ""), name.toUpperCase()];
}

export function BrandGroupsEditor() {
  const [groups, setGroups] = useState<BrandGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [groupTitle, setGroupTitle] = useState("");
  const [creatingGroup, setCreatingGroup] = useState(false);
  const [brandDraft, setBrandDraft] = useState<
    Record<string, { name: string; logo?: File; busy: boolean }>
  >({});
  const [rowBusy, setRowBusy] = useState<string | null>(null);

  const refresh = async () => {
    const items = await listBrandGroups();
    setGroups(items);
  };

  useEffect(() => {
    let cancelled = false;
    void listBrandGroups()
      .then((items) => {
        if (!cancelled) {
          setGroups(items);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "No se pudieron cargar los grupos.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleCreateGroup = async () => {
    const titulo = groupTitle.trim();
    if (!titulo || creatingGroup) return;
    setCreatingGroup(true);
    setError(null);
    try {
      await createBrandGroup(titulo);
      setGroupTitle("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo crear el grupo.");
    } finally {
      setCreatingGroup(false);
    }
  };

  const handleDeleteGroup = async (groupId: string) => {
    setRowBusy(`group-${groupId}`);
    setError(null);
    try {
      await deleteBrandGroup(groupId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo eliminar el grupo.");
    } finally {
      setRowBusy(null);
    }
  };

  const handleAddBrand = async (groupId: string) => {
    const draft = brandDraft[groupId];
    const name = draft?.name.trim() ?? "";
    if (!name) return;
    setBrandDraft((current) => ({
      ...current,
      [groupId]: { ...current[groupId], name, logo: current[groupId]?.logo, busy: true },
    }));
    setError(null);
    try {
      await createBrand({
        name,
        aliases: brandAliases(name),
        logo: draft?.logo,
        group_id: groupId,
      });
      setBrandDraft((current) => ({
        ...current,
        [groupId]: { name: "", logo: undefined, busy: false },
      }));
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo agregar la marca.");
      setBrandDraft((current) => ({
        ...current,
        [groupId]: { ...current[groupId], busy: false },
      }));
    }
  };

  const handleToggleActivo = async (brandId: string, activo: boolean) => {
    setRowBusy(brandId);
    setError(null);
    try {
      await patchBrand(brandId, { activo });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo actualizar la marca.");
    } finally {
      setRowBusy(null);
    }
  };

  const handleLogo = async (brandId: string, logo: File | undefined) => {
    if (!logo) return;
    setRowBusy(brandId);
    setError(null);
    try {
      await patchBrand(brandId, { logo });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo subir el logo.");
    } finally {
      setRowBusy(null);
    }
  };

  const handleDeleteBrand = async (brandId: string) => {
    setRowBusy(brandId);
    setError(null);
    try {
      await deleteBrand(brandId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo eliminar la marca.");
    } finally {
      setRowBusy(null);
    }
  };

  if (loading) {
    return (
      <div className="space-y-3" aria-busy="true" aria-label="Cargando grupos">
        {[0, 1].map((key) => (
          <div
            key={key}
            className="h-24 animate-pulse rounded-xl border border-border/70 bg-muted/30"
          />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <div className="flex-1">
          <Label htmlFor="new-group-title" className="sr-only">
            Título del grupo
          </Label>
          <Input
            id="new-group-title"
            value={groupTitle}
            onChange={(event) => setGroupTitle(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void handleCreateGroup();
              }
            }}
            placeholder="Título del grupo"
            className="h-11 bg-background/60"
          />
        </div>
        <Button
          type="button"
          variant="secondary"
          className="h-11 gap-2 px-4"
          onClick={() => void handleCreateGroup()}
          disabled={!groupTitle.trim() || creatingGroup}
        >
          {creatingGroup ? (
            <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
          ) : (
            <Plus className="size-4" aria-hidden="true" />
          )}
          Crear grupo
        </Button>
      </div>

      {error ? <p className="text-xs text-destructive">{error}</p> : null}

      {groups.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border/70 px-4 py-6 text-center text-sm text-muted-foreground">
          Crea un grupo para organizar las marcas que vas a medir en cada partido.
        </div>
      ) : (
        <div className="space-y-3">
          {groups.map((group, index) => {
            const draft = brandDraft[group.id] ?? { name: "", logo: undefined, busy: false };
            return (
              <details
                key={group.id}
                open={index === 0}
                className="rounded-xl border border-border/70 bg-background/35"
              >
                <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-3 [&::-webkit-details-marker]:hidden">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-foreground">{group.titulo}</p>
                    <p className="font-mono text-[10px] text-muted-foreground">
                      {group.brands.length} marca{group.brands.length === 1 ? "" : "s"}
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-9 text-muted-foreground hover:text-destructive"
                    disabled={rowBusy === `group-${group.id}`}
                    onClick={(event) => {
                      event.preventDefault();
                      void handleDeleteGroup(group.id);
                    }}
                    aria-label={`Eliminar grupo ${group.titulo}`}
                  >
                    <Trash2 className="size-4" aria-hidden="true" />
                  </Button>
                  <ChevronDown className="size-4 text-muted-foreground" aria-hidden="true" />
                </summary>
                <div className="space-y-3 border-t border-border/60 px-3 py-3">
                  {group.brands.length ? (
                    <div className="space-y-2">
                      {group.brands.map((brand) => {
                        const activo = brand.activo !== false;
                        const busy = rowBusy === brand.id;
                        return (
                          <div
                            key={brand.id}
                            className={`flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2.5 transition-colors ${
                              activo
                                ? "border-primary/30 bg-primary/5"
                                : "border-border/70 bg-muted/20"
                            }`}
                          >
                            <span
                              className={`min-w-0 flex-1 truncate text-sm font-medium ${
                                activo ? "text-foreground" : "text-muted-foreground"
                              }`}
                            >
                              {brand.nombre}
                            </span>
                            <Switch
                              checked={activo}
                              disabled={busy}
                              onCheckedChange={(checked) =>
                                void handleToggleActivo(brand.id, checked)
                              }
                              aria-label={`${activo ? "Desactivar" : "Activar"} ${brand.nombre}`}
                            />
                            <label className="flex min-h-9 cursor-pointer items-center gap-2 rounded-md border border-transparent px-2 text-xs text-muted-foreground transition-colors hover:border-border hover:text-foreground">
                              <Input
                                type="file"
                                accept="image/png,image/jpeg,image/webp"
                                className="sr-only"
                                disabled={busy}
                                onChange={(event) => {
                                  void handleLogo(brand.id, event.target.files?.[0]);
                                  event.target.value = "";
                                }}
                              />
                              <UploadCloud className="size-3.5" aria-hidden="true" />
                              {brand.has_logo ? "Logo cargado" : "Logo"}
                            </label>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="size-9 text-muted-foreground hover:text-destructive"
                              onClick={() => void handleDeleteBrand(brand.id)}
                              disabled={busy}
                              aria-label={`Eliminar ${brand.nombre}`}
                            >
                              {busy ? (
                                <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
                              ) : (
                                <Trash2 className="size-4" aria-hidden="true" />
                              )}
                            </Button>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      Este grupo todavía no tiene marcas.
                    </p>
                  )}
                  <div className="flex flex-wrap gap-2">
                    <Input
                      value={draft.name}
                      onChange={(event) =>
                        setBrandDraft((current) => ({
                          ...current,
                          [group.id]: {
                            ...current[group.id],
                            name: event.target.value,
                            logo: current[group.id]?.logo,
                            busy: false,
                          },
                        }))
                      }
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          void handleAddBrand(group.id);
                        }
                      }}
                      placeholder="Nombre de la marca"
                      className="h-10 min-w-40 flex-1 bg-background/60"
                      disabled={draft.busy}
                    />
                    <label className="flex h-10 cursor-pointer items-center gap-2 rounded-lg border border-border/70 px-3 text-xs text-muted-foreground hover:border-primary/50 hover:text-foreground">
                      <input
                        type="file"
                        accept="image/png,image/jpeg,image/webp"
                        className="sr-only"
                        disabled={draft.busy}
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          event.target.value = "";
                          setBrandDraft((current) => ({
                            ...current,
                            [group.id]: {
                              name: current[group.id]?.name ?? "",
                              logo: file,
                              busy: false,
                            },
                          }));
                        }}
                      />
                      <UploadCloud className="size-3.5" aria-hidden="true" />
                      {draft.logo ? "Logo listo" : "Logo"}
                    </label>
                    <Button
                      type="button"
                      variant="secondary"
                      className="h-10 gap-2"
                      onClick={() => void handleAddBrand(group.id)}
                      disabled={!draft.name.trim() || draft.busy}
                    >
                      {draft.busy ? (
                        <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
                      ) : (
                        <Plus className="size-4" aria-hidden="true" />
                      )}
                      Agregar
                    </Button>
                  </div>
                </div>
              </details>
            );
          })}
        </div>
      )}
    </div>
  );
}
