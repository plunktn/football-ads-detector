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

## Instalación local (operadores / Claude)

Guía paso a paso + prompt copy-paste para dejar UI y API corriendo en tu
máquina (recomendado para partidos grandes ~5 GB):

→ **[docs/INSTALL_LOCAL.md](docs/INSTALL_LOCAL.md)**

Resumen rápido si ya conoces el repo:

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && cd ..
cd frontend && npm install && cd ..
./start.sh    # UI :43123 · API :43124 · parar con ./stop.sh
```

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
   archivo (vacío = detección por marcador). Si cargás ambos, el job **no**
   escanea el marcador (`overrides_only`). Los offsets son por partido —
   no copies un 2T de otro video.
3. El job fuerza ventana `full` y verifica cada pauta 1T/2T.
4. Excel: `Resumen LED` | `Salidas LED` | `Cumplimiento` | `Dudosas` | `Extras`
   (hoja `Fijas` solo si `include_fixed=true`).

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
2. Si el kickoff auto falla, fija offsets **medidos en ese archivo** (1T ≈
   saque; 2T ≈ reinicio tras entretiempo — no reutilices 3521 de otro partido).
3. Corre `playlist_verify` y abre `informe.xlsx`.
4. Revisa hoja **Dudosas** antes de tratar un MISS como incumplimiento.
5. OCR flojo → preferir `AMBIGUOUS` + captura; no inventar métricas.
6. Discovery sin playlist debe seguir funcionando igual (smoke de UI).

Crops de depuración en `data/jobs/{id}/debug/`; resultado en
`result.json` e `informe.xlsx`.

## Limitaciones v1

- Muestreo de análisis configurable: **1 fps** (default, discovery barato) o
  **2 fps** (~2× CPU). La duración comercial LED fusiona huecos cortos de la
  misma marca; ver la sección de fusión.
- Procesamiento local en CPU; paneos, blur o tipografías pequeñas pueden
  fallar el OCR.
- Fondos de arco y overlays virtuales de broadcast no se inventarian.
- Discovery no inventa marcas fuera del catálogo o de la playlist.
- Vallas fijas están desactivadas por defecto (`include_fixed=false`); no
  contaminan el total LED.

## Duración LED: fusión e histéresis

Una aparición continua (u OCR que parpadea) de la **misma marca** en la
**misma mitad** sale como un solo intervalo. La duración es el tramo de
reloj: desde el primer hit hasta el final del último sample
(`último + 1/sample_fps`), hueco puenteado incluido. No se suman migas de
1–2 s. El Excel (`Resumen LED` / `Salidas LED`) y el informe del catálogo
usan esos intervalos.

No se fusiona si en el hueco hay otra marca en positivo, ni a través de
1T/2T. Las vallas fijas siguen con hueco de 3 s y no usan este puente.

| Variable | Default | Efecto |
| --- | --- | --- |
| `LED_MERGE_GAP_SEC` | 8 | Hueco máximo, en segundos, que sigue siendo la misma salida. |
| `LED_OFF_HOLD_SEC` | igual al gap | Ausencia para cerrar la salida (histéresis de apagado). Si es menor que el gap, un segundo paso igual junta huecos hasta el gap cuando no hubo otra marca. |
| `LED_ON_CONFIRM_SEC` | 0 | Segundos positivos seguidos para abrir (0 = abre con el primer hit). |

Un valor inválido o negativo vuelve al default. El objetivo de auditoría
(±15–20% en tramos no dudosos) se mide con minutos gold; esta fusión no lo
garantiza sola.

## Minutos gold

Para comparar el detector con clips etiquetados a mano, sin re-auditar el
partido:

1. Copia `backend/eval/gold/clips/example.json`.
2. Completa `labels`: `brand`, `brand_id` si lo tienes, `start_s`, `end_s`,
   `quality` (`good` \| `ok` \| `bad`) y `doubtful`. Duración = `end_s - start_s`.
   No solapes la misma marca. No subas el video.
3. `doubtful: true` marca ilegibles o tramos que no entran al error. `quality`
   queda anotada y no cambia el cálculo.

```bash
cd backend
python eval/gold/compare_gold.py --gold eval/gold/clips/tu_clip.json
python eval/gold/compare_gold.py \
  --gold eval/gold/clips/tu_clip.json \
  --detector data/jobs/<id>/result.json \
  --tolerance 20
```

`--detector` puede ser una lista de segmentos o el `result.json` del job
(solo marcas LED, no fijas).

**Pass:** en tramos no dudosos, el error de duración por marca queda dentro
de ±15–20% (`--tolerance 20` por defecto; usa `15` para el extremo estricto).
El script imprime también el % de tiempo etiquetado como dudoso. El ejemplo
del repo es solo formato: sin `--detector` el error sale `n/a` y no es una
medición del detector.

Detalle corto en `backend/eval/gold/README.md`.

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
