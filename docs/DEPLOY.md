# Deploy: Railway (API) + Cloudflare Pages (UI)

## Backend en Railway

1. Nuevo **service** en tu proyecto Railway (mismo workspace que Plunkton).
2. Conectar repo `Roiner994/football-ads-detector`, branch `master`.
3. Railway detecta `Dockerfile` + `railway.toml` en la raíz.
4. **Volume** montado en `/app/data` (jobs + SQLite).
5. Variables de entorno:

| Variable | Valor |
| --- | --- |
| `KEEP_JOB_VIDEOS` | `false` (default; libera disco tras cada job) |
| `CORS_ORIGINS` | URL del front en Cloudflare, ej. `https://football-ads.pages.dev` |

6. Plan con **≥ 2 GB RAM** recomendado (OpenCV + OCR).
7. Dominio público Railway → copiar URL para el front.

Health check: `GET /health` → `{ "ok": true }`.

## Frontend en Cloudflare Pages

1. Conectar el mismo repo GitHub.
2. **Root directory:** `frontend`
3. **Build command:** `npm run build`
4. **Framework preset:** Next.js
5. Variable de build:

```
NEXT_PUBLIC_API_URL=https://<tu-api>.up.railway.app
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
