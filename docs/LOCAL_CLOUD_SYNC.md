# Local + cloud: fuente de verdad y análisis

**Decisión:** cloud guarda config y resultados; el video se analiza en local; sync sube artefactos del partido (no el MP4).

## Quick path (fase 2)

1. Operador abre **prod** → edita marcas / refs / estadios (única fuente de verdad).
2. Local **pull** de esa config antes de analizar.
3. Local corre el partido (video nunca sube).
4. Tras confirmar catálogo, local **push** del job a cloud.
5. Cloud retiene últimos **50** jobs; borrar un partido borra toda su data.

## Roles

| Pieza | Dónde vive | Quién edita |
|-------|------------|-------------|
| Marcas, aliases, brand refs, estadios | Cloud | Solo prod (UI cloud) |
| Video del partido | Disco local | Nunca a cloud |
| Catálogo confirmado + informe | Local → cloud | Push al terminar |
| Crops / thumbs del catálogo | Local → cloud | Push al terminar (artefactos chicos) |
| Updates de refs nacidos del partido | Local → cloud | Push si aportan a la biblioteca |

## Retención y borrado

| Regla | Detalle |
|-------|---------|
| Tope | Últimos **50** partidos en cloud |
| Al superar 50 | Rotar el más viejo (cascada) |
| Borrar partido | Elimina job + catálogo + crops/thumbs + metadatos de ese id |
| Video crudo | No se almacena en cloud |

## Qué no hacer (anti-pisones)

- No editar marcas/refs/estadios en local como verdad (evita overwrite al sync).
- No merge “last write wins” en config.
- No subir el MP4 del partido a Railway/Pages.

Si local está offline: trabaja con la última config bajada; el push de resultados espera red.

## Alcance por fases

| Fase | Entrega |
|------|---------|
| **1 (ahora)** | Brand refs + UX catálogo en prod (sin sync híbrido) |
| **2** | API sync: `GET /sync/config`, `POST /sync/jobs/{id}` (artefactos), retención 50, delete cascada |
| **3** | UI local: “Sincronizar config” / “Publicar partido”; matching híbrido con refs (ver `BRAND_REFS.md`) |

## Checklist fase 2

- [ ] Config cloud-only documentada en UI local (solo lectura o “abre prod para editar”)
- [ ] Pull config idempotente
- [ ] Push job: informe + catálogo + crops + refs nuevas opcionales
- [ ] Retención 50 + delete cascada
- [ ] Tope de tamaño por job (rechazar push si crops > umbral)
- [ ] Auth mínima del sync (token operador)

## Next step

Implementar fase 2 tras validar fase 1 en prod. Detalle de matching con refs: `docs/BRAND_REFS.md`. Deploy: `docs/DEPLOY.md`.
