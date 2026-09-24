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
2. Opcional: override de **kickoff 1T** e **inicio 2T** en segundos de
   archivo (vacío = detección por marcador). Si cargás ambos, el job **no**
   escanea el marcador (`overrides_only`). Los offsets son por partido —
   no copies un 2T de otro video. El bloque está en el formulario de análisis
   (también en discovery), no solo dentro de la playlist.
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
   saque; 2T ≈ reinicio tras entretiempo — no reutilices 3521 ni 4145 de otro
   partido). Si el marcador no vuelve a 00:00, elige reloj continuo.
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

## Marcas de interés y OCR

Los segundos comerciales salen de las marcas en
`backend/config/interest_brands.yaml` (Ecuabet, NETTPLUS, LIONS, 1xbet,
SIETE.COM, GRAND AVIATION). Cada alias, incluido un fragmento de OCR como
`NETT OIUS` o `ECUEBET`, resuelve al id canónico. Para sumar una variante
nueva, edita ese YAML: no hace falta tocar el matcher.

La lista de playlist (`backend/app/config/brand_aliases.yaml`) sigue aparte.
Las vallas fijas no usan la lista de interés ni el puente de 8 s.

## Dudoso / no medible

Si la valla está en cuadro pero el OCR no alcanza (texto ilegible, coincidencia
débil o crop de mala calidad), ese tramo se fusiona en un intervalo de reloj
con `doubtful: true` y `measurable: false`. Esos segundos:

- no entran al total de la marca;
- no entran al margen de ±15–20% (el harness gold los resta de ambos lados);
- aparecen en la hoja **Dudosas** del Excel y en el informe, para revisión.

Un plano sin valla (close-up, bumper, wide) no es dudoso: la LED no estaba en
cuadro. No hace falta revisarlo.

## Cola de revisión

Después del análisis, la revisión abre en **Dudosos y baja confianza**. La
exposición ya medida queda plegada. Asigna una marca de interés si reconoces
el sponsor; si el tramo sigue ilegible, déjalo sin asignar.

El informe (`/informe`) encabeza los **segundos en pantalla** de las marcas de
interés. El bloque **No medible** lista solo los rangos que hay que mirar.

## Kickoff y segundo tiempo

Los overrides viven en `backend/config/clock_overrides.yaml` y en
`GET` / `PUT /clock-overrides/{id}`. Quedan en el equipo del operador: **no**
entran al sync de marcas/estadios.

| `clock_mode` | Qué hace |
| --- | --- |
| `reset` | El marcador vuelve cerca de 00:00 en el 2T. Si no lo encuentra, avisa y el LED de esa mitad no se suma. |
| `continuous` | El reloj no se reinicia. No se busca una vuelta a 00:00. Sin `second_half_start_sec`, el 2T no entra al informe. |

Hecho de QA: **Libertad vs Orense** es reloj continuo y el 2T del archivo
completo arranca ≈ **4145 s** de pared. Ese número no es una duración de
marca y no se aplica solo: hay que elegir el perfil (o escribir el segundo).
El kickoff de 1T de ese archivo todavía hay que medirlo.

Si el partido es `full` y el 2T no entra, el resultado trae
`second_half_included: false` y un warning. Esos segundos no se suman en
silencio.

## Minutos gold

Para comparar el detector con clips etiquetados a mano, sin re-auditar el
partido:

1. Copia `backend/eval/gold/clips/example.json` o parte de
   `clips/synthetic_interest.json`.
2. Completa `labels`: `brand`, `brand_id`, `start_s`, `end_s` (segundos del
   reproductor, no el índice de frame), `quality` (`good` \| `ok` \| `bad`),
   `doubtful` y `measurable`. Duración = `end_s - start_s`. No solapes la
   misma marca. No subas el video.
3. `doubtful: true` o `measurable: false` = ilegible. No entra al error.
4. En `interest_brands` lista los ids de `interest_brands.yaml`. En
   `expected_seconds` escribe la suma medible de cada una. Si no cuadra con
   las filas, el reporte es FAIL.
5. `synthetic_interest.json` es un fixture inventado. No lo cites como
   medición de un partido.

```bash
cd backend
python eval/gold/compare_gold.py \
  --gold eval/gold/clips/synthetic_interest.json \
  --detector eval/gold/fixtures/synthetic_interest_detector.json \
  --tolerance 15
python eval/gold/compare_gold.py \
  --gold eval/gold/clips/tu_clip.json \
  --detector data/jobs/<id>/result.json \
  --tolerance 20
```

`--detector` puede ser una lista de segmentos o el `result.json` del job
(marcas LED y `doubtful_segments`; las fijas no entran).

**Pass:** en tramos no dudosos de las marcas de interés, el error de duración
queda dentro de ±15–20% (`--tolerance 20` por defecto; `15` es el extremo
estricto). El reporte dice PASS o FAIL, cuántos segundos dudosos quedaron
fuera y cuántos `doubtful_segments` del detector se restaron. Sin
`--detector` el error sale `n/a`.

Cómo etiquetar un clip real: `backend/eval/gold/README.md`.

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
