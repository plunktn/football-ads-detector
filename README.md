# Football Ads Detector

Herramienta local para medir la exposición de marcas en las vallas LED
laterales de un partido de fútbol. Sube un partido completo o los dos
tiempos, carga la lista de marcas y recibe apariciones, tiempo total y frames
de inicio.

El sistema detecta el césped, toma la franja luminosa inmediatamente encima
de su borde y aplica OCR únicamente allí; las lonas fijas de arriba y los
fondos de arco quedan fuera del análisis LED (en discovery también se
reportan fijas por separado).

## Requisitos

- Python 3.11+
- Node.js 20+
- CPU; RapidOCR descarga sus modelos en el primer uso

## Desarrollo local

Backend:

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 43124
```

Frontend, en otra terminal:

```bash
cd frontend
npm install
npm run dev
```

Abre http://127.0.0.1:43123. La API queda disponible en
http://127.0.0.1:43124 y responde `{ "ok": true }` en `/health`.

Si necesitas otra dirección para la API, define:

```bash
NEXT_PUBLIC_API_URL=http://127.0.0.1:43124
```

## Uso: discovery vs playlist_verify

### Discovery (default)

1. Video full o 1T+2T.
2. Lista de marcas (nombres / aliases / logos opcionales).
3. Ventana 5min / 10min / custom / partido entero.
4. **Analizar** → exposición LED + fijas + CSV. Sin playlist.

### Playlist verify (auditoría de reporte Lions)

1. Marca **Verificar playlist/reporte** y sube el xlsx multi-hoja
   (`PREVIA` / `PRIMER TIEMPO` / `ENTRETIEMPO` / `SEGUNDO TIEMPO` / `POST`)
   con columnas `CLIENTE`, `MINUTO` (`0.15` = 0:15), `DURACIÓN` (default 15s).
2. Opcional: override de **offset kickoff 1T** e **inicio 2T** en segundos de
   archivo (vacío = detección por marcador).
3. El job fuerza ventana `full` y verifica cada pauta 1T/2T.
4. Excel: `Resumen` | `Salidas` | `Cumplimiento` | `Dudosas` | `Extras`.

`hit_rate` = `HIT / (HIT + MISS)`. Los estados dudosos y `PAST_EOF` **no**
entran al denominador.

| Status | Significado |
| --- | --- |
| HIT | Marca clara en ventana (Δ ≤ 20s) |
| MISS | Plano LED usable y la marca no aparece |
| NO_EVIDENCE | Close-up / bumper / wide sin banda LED |
| AMBIGUOUS | OCR/logo flojo; revisar captura |
| OFFSET | Marca vista fuera de ±20s (±60s vecinos) |
| PAST_EOF | Minuto mapeado más allá de la duración del archivo |

Overlays de TV (Zapping, xtrim, SHOWTIME, etc.) no cuentan.

### Checklist primera corrida real

1. Video full match (o 1T+2T split) + playlist Lions xlsx.
2. Si el kickoff auto falla, fija offsets (ej. TU vs Cuenca / Lib vs Ore:
   kickoff ~282s, 2T ~3521s).
3. Corre `playlist_verify` y abre `informe.xlsx`.
4. Revisa hoja **Dudosas** antes de tratar un MISS como incumplimiento.
5. OCR flojo → preferir `AMBIGUOUS` + captura; no inventar métricas.
6. Discovery sin playlist debe seguir funcionando igual (smoke de UI).

Crops de depuración en `data/jobs/{id}/debug/`; resultado en
`result.json` e `informe.xlsx`.

## Limitaciones v1

- Muestreo de análisis a 1 FPS (P1: 0.5s en ventanas verify).
- Procesamiento local en CPU; paneos, blur o tipografías pequeñas pueden
  fallar el OCR.
- Fondos de arco y overlays virtuales de broadcast no se inventarian.
- Discovery no inventa marcas fuera del catálogo o de la playlist.

## Almacenamiento de jobs

Por defecto, al terminar un análisis exitoso se borran el video subido y la
carpeta `debug/` del job. Se conservan `result.json`, `informe.xlsx` y
metadatos (pocos MB por corrida).

Para conservar videos en local (p. ej. revisar frames después):

```bash
export KEEP_JOB_VIDEOS=true
```

En Railway no hace falta definir la variable: el default ya libera disco.

## Verificación

```bash
cd backend
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/smoke_test.py
cd ../frontend
npm run lint
npm run build
```
