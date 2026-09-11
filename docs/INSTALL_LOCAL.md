# Instalación local — Football Ads Detector

Para operadores y para un agente (Claude / Cursor): deja UI + API corriendo en
esta máquina. Los partidos grandes (~5 GB) se analizan **aquí**; el video no
sale a internet.

Sync futuro (config en cloud, resultados del partido hacia cloud): ver
`docs/LOCAL_CLOUD_SYNC.md`.

| | URL |
| --- | --- |
| UI | http://127.0.0.1:43123 |
| API | http://127.0.0.1:43124 |
| Health | `GET /health` → `{"ok":true}` |

---

## Prompt para Claude / Cursor (copiar y pegar)

```text
Clona el repo plunktn/football-ads-detector (o usa el checkout que ya tengo),
configura el entorno e inicia backend + frontend en local siguiendo
docs/INSTALL_LOCAL.md al pie de la letra.

Al terminar debes verificar:
1) curl -sf http://127.0.0.1:43124/health → {"ok":true}
2) La UI responde en http://127.0.0.1:43123
3) Dime las URLs y cómo parar con ./stop.sh

No despliegues a Railway ni toques producción.
```

---

## Requisitos

- macOS o Linux
- Git
- Python **3.11+**
- Node.js **20+**
- Puertos libres **43123** (UI) y **43124** (API)
- Disco libre generoso: el video del partido + `data/jobs/` (jobs, frames, catálogo)

---

## Setup (una vez)

### 1. Clonar

```bash
git clone git@github.com:plunktn/football-ads-detector.git
cd football-ads-detector
```

HTTPS si no tienes SSH:

```bash
git clone https://github.com/plunktn/football-ads-detector.git
cd football-ads-detector
```

### 2. Backend (Python)

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd ..
```

### 3. Frontend (Node)

```bash
cd frontend
npm install
cd ..
```

`./start.sh` también corre `npm install` si falta `node_modules`, pero el venv
**debe** existir antes (el script falla si no hay `backend/.venv`).

---

## Arrancar

Desde la raíz del repo:

```bash
chmod +x start.sh stop.sh   # solo la primera vez, si hace falta
./start.sh
```

Salida esperada: API OK + UI OK, y los links de arriba.

Parar:

```bash
./stop.sh
```

Logs en `.run/backend.log` y `.run/frontend.log`.

### Arranque manual (si no usas start.sh)

Terminal A:

```bash
cd backend
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 43124 --reload
```

Terminal B:

```bash
cd frontend
npm run dev
```

Por defecto el front apunta a `http://127.0.0.1:43124`. Solo si cambias el
puerto del API:

```bash
export NEXT_PUBLIC_API_URL=http://127.0.0.1:43124
```

---

## Smoke check

```bash
curl -sf http://127.0.0.1:43124/health
# → {"ok":true}

curl -sf -o /dev/null -w "%{http_code}\n" http://127.0.0.1:43123/
# → 200
```

En el navegador: abre la UI → carga un **clip corto** de prueba → Analizar.
La primera corrida puede tardar: RapidOCR descarga modelos.

---

## Uso del operador (partido completo)

1. Ten el MP4 en el disco local (Drive → descargar a la máquina).
2. UI local → video + grupo de marcas + ventana (5 min / full / etc.).
3. **Analizar** → revisión de catálogo → confirmar → **Ver informe** si aplica.
4. Borrar análisis viejos desde “Análisis recientes” para liberar disco.

Full match (~5 GB) es viable en local porque el archivo no se sube a la nube.

Referencias visuales por marca (imágenes + keyframes de video): ver
[`docs/BRAND_REFS.md`](BRAND_REFS.md). La fase 2 usará esas refs para matching LED.

---

## Disco y `data/jobs`

- Jobs y artefactos viven bajo `data/jobs/` (y marcas en `data/brands/`).
- Por defecto, al completar un job se purgan video y `debug/` (`KEEP_JOB_VIDEOS=false`).
- Para conservar videos locales al terminar:

```bash
export KEEP_JOB_VIDEOS=true
./start.sh
```

---

## Troubleshooting

| Problema | Qué hacer |
| --- | --- |
| `falta backend/.venv` | Completa el paso Backend arriba. |
| Puerto 43123/43124 ocupado | `./stop.sh` o `FRONTEND_PORT=43125 ./start.sh` (UI) / `BACKEND_PORT=43126 ./start.sh` (API). |
| UI no levanta | Mira `.run/frontend.log` (busca `EADDRINUSE`). |
| API no responde | Mira `.run/backend.log`; reinstala deps del venv. |
| Primer análisis muy lento | Normal: descarga de modelos OCR. |
| “CORS” en local | No aplica entre `127.0.0.1:43123` y `:43124` con el setup default. |

---

## Fuera de alcance de esta guía

Despliegue Railway / Cloudflare Pages, ingest desde Google Drive, y política
de disco en la nube. Eso se documenta aparte cuando exista un flujo cloud para
partidos grandes.
