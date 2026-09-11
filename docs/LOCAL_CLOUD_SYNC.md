# Local + cloud: fuente de verdad y análisis

**Decisión:** cloud (Railway) guarda la config compartida; el video se analiza en local; sync de **marcas/refs/estadios** ya está implementado. Push de jobs/informes = fase siguiente.

## Quick path (config sync — listo)

1. Railway tiene `SYNC_TOKEN`.
2. Local: `backend/.env` con `CLOUD_API_URL` + el mismo `SYNC_TOKEN`.
3. Al arrancar la API local hace **pull** de cloud.
4. Editas marcas en local **o** en [pages.dev](https://football-ads-detector.pages.dev); en local los cambios hacen **push** automático.
5. En Configuración: botones **Bajar de cloud** / **Subir a cloud**.
6. Video del partido: solo disco local (nunca sube).

## Roles

| Pieza | Dónde vive | Quién edita |
|-------|------------|-------------|
| Marcas, aliases, brand refs, estadios | Cloud (verdad) + cache local | Local o prod; sync con token |
| Video del partido | Disco local | Nunca a cloud |
| Catálogo / informe del job | Local (por ahora) | Fase jobs: push a cloud |

## API

| Ruta | Uso |
|------|-----|
| `GET /sync/config` | ZIP config (header `X-Sync-Token`) |
| `PUT /sync/config` | Aplica ZIP (token) |
| `GET /sync/status` | Si el local tiene cloud configurado |
| `POST /sync/pull` | Local → descarga cloud |
| `POST /sync/push` | Local → sube a cloud |

## Retención jobs (pendiente)

| Regla | Detalle |
|-------|---------|
| Tope | Últimos **50** partidos en cloud |
| Borrar partido | Cascada de artefactos del job |
| Video crudo | No en cloud |

## Qué no hacer

- No subir el MP4 del partido.
- No compartir `SYNC_TOKEN` en el repo ni en chats públicos.
- No poner `CLOUD_API_URL` en Railway apuntando a sí mismo.

## Checklist

- [x] Sync config ZIP + token
- [x] Pull al arrancar local
- [x] Push tras CRUD config
- [x] UI Configuración sync
- [ ] Push de jobs / retención 50
- [ ] Matching híbrido con refs (`BRAND_REFS.md`)

## Next step

Jobs → cloud. Matching: `docs/BRAND_REFS.md`. Deploy: `docs/DEPLOY.md`.
