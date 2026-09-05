# Deploy: Railway (API) + Cloudflare Pages (UI)

## Backend en Railway

Proyecto creado en workspace **Plunkton's Projects** (separado de `plunkton-crm` y `plunkton_agentic`).

| | |
| --- | --- |
| Proyecto | `football-ads-detector` |
| API | https://football-ads-detector-production.up.railway.app |
| Volume | `/app/data` (5 GB) |
| Dashboard | https://railway.com/project/914e459c-8d72-471b-84c7-e111163e996d |

1. Service conectado al repo `plunktn/football-ads-detector`.
2. `Dockerfile` + `railway.toml` en la raíz.
3. **Volume** montado en `/app/data` (jobs + SQLite).
4. Variables de entorno:

| Variable | Valor |
| --- | --- |
| `KEEP_JOB_VIDEOS` | `false` (default; libera disco tras cada job) |
| `CORS_ORIGINS` | URL del front en Cloudflare, ej. `https://football-ads.pages.dev` |

6. Plan con **≥ 2 GB RAM** recomendado (OpenCV + OCR).
7. Dominio público Railway → copiar URL para el front.

Health check: `GET /health` → `{ "ok": true }`.

## MCP de Railway (Cursor)

El MCP `https://mcp.railway.com` es por **cuenta/workspace**, no por proyecto.
Plunkton y football-ads-detector comparten el mismo OAuth de Railway.

Este repo incluye `.cursor/mcp.json` con el mismo server que Plunkton.
No hace falta un MCP distinto por proyecto.

## Frontend en Cloudflare Pages

1. Conectar repo `plunktn/football-ads-detector` en la cuenta Cloudflare de Plunkton.
2. **Root directory:** `frontend`
3. **Build command:** `npm run build`
4. **Framework preset:** Next.js
5. Variable de build:

```
NEXT_PUBLIC_API_URL=https://football-ads-detector-production.up.railway.app
```

6. Deploy. Abrir la URL de Pages y probar un job con video corto.

## Smoke test post-deploy

1. `/health` responde OK.
2. Subir un clip corto (< 1 min).
3. Job completa → descargar CSV/XLSX.
4. Verificar que el disco en Railway no crece ~4 GB por corrida (videos se purgan al terminar).

## Local vs producción

| | Local | Producción |
| --- | --- | --- |
| UI | `:43123` | Cloudflare Pages |
| API | `:43124` | Railway |
| Videos post-job | `KEEP_JOB_VIDEOS=true` opcional | default `false` |
