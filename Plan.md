# PLAN.md — `football-ads-detector`

Documento **ejecutable**. Un agente más pequeño debe seguirlo **en orden**, sin reinventar el stack ni el algoritmo de ROI. Si algo no está aquí, no lo agregues en v1.

---

## 0. Rol del agente que implementa

1. Crear el proyecto completo `football-ads-detector` en la carpeta myBrain, ya estas en la carpeta donde vas a crear el proyecto pero verifica por si acaso.
2. Dejar una app usable: UI web + backend de análisis de video.
3. Commitear y pushear al terminar cada fase (0–8).
4. Al final: README, servidor de desarrollo levantado, barra de progreso real, resultados reales.

**Idioma de la UI:** español. **Idioma del código:** inglés (nombres de archivos, funciones, JSON keys).

---

## 1. Qué es el producto

Herramienta para **medir publicidad en las vallas LED laterales** de un partido de fútbol (broadcast).

El usuario:

1. Sube **un video** del partido **o dos videos** (primer tiempo + segundo tiempo).
2. Carga una **lista de marcas** (nombre obligatorio, logo opcional).
3. Elige cuánto analizar: **5 minutos**, **10 minutos** o **partido entero**.
4. Ve una **barra de progreso**.
5. Recibe, por marca:

- cuántas **veces** apareció (tramos continuos, no fotogramas sueltos)
- **minutos** y **segundos** de exposición en la LED
- **frames de inicio** de cada aparición

### El problema que no puedes fallar

Hay **dos capas** de publicidad:

| Capa                   | Dónde está                                                            | ¿Se cuenta? |
| ---------------------- | --------------------------------------------------------------------- | ----------- |
| **Valla LED dinámica** | Franja horizontal **a ras de grama**, brilla, **cambia de contenido** | **SÍ**      |
| **Lonas fijas**        | Justo **arriba** de la LED, mate, no cambian                          | **NO**      |

Tampoco se cuentan las vallas **detrás de los arcos**. Solo laterales (cámara de costado).

---

## 2. Caso de prueba canónico (obligatorio)

Mismo partido, overlay `LigaEcuabet`, `LIB` vs `ORE`.

**Frame A — reloj ~03:25 (1T)**

- LED (abajo, pegada al césped): **NETT plus** (texto blanco sobre cyan/azul, luminosa, repetida a lo largo de la banda).
- Lona fija (arriba de la LED): también puede decir NETT plus, fondo blanco, sin glow.
- **Resultado correcto:** contar NETT plus. Esa aparición empieza cerca del segundo 205 de 1T.

**Frame B — reloj ~03:27 (1T), dos segundos después**

- LED: **LIONS SPORTS & MEDIA** (blanco sobre azul oscuro, o blanco con letras rojo/azul).
- Lona fija de arriba: **NETTPLUS** sigue visible.
- **Resultado correcto:** contar Lions Sports & Media. **No** sumar NETT plus en este frame. NETT plus de la lona fija no existe para el sistema.

Si tu pipeline cuenta NETT plus en el frame B, el ROI está mal (estás leyendo las lonas de arriba). **Corrige el recorte, no el OCR.**

---

## 3. Fuera de alcance (v1) — no implementar

- Entrenar YOLOv8, SAM, detectores de logos, ni ningún modelo custom.
- GPU, Docker, auth, base de datos, colas Redis/Celery.
- Vallas detrás del arco, vallas de corner a cámara de fondo, supergráfico de broadcast (marcador, “VIVO”, watermarks).
- Identificar automáticamente marcas que el usuario no cargó.
- App móvil nativa.
- Procesar 30/60 fps nativos del MP4.

La info de “entrenar YOLO/SAM” del briefing extra **se descarta en v1**. Usamos geometría (césped → franja contigua) + OCR.

---

## 4. Stack tecnológico (obligatorio — no cambiar)

### Frontend

- Next.js 15 (App Router)
- TypeScript
- Tailwind CSS
- shadcn/ui (`button`, `input`, `label`, `card`, `progress`, `table`, `badge`, `tabs`, `separator`, `scroll-area`, `tooltip`, `select`)
- Puerto **43123** (`0.0.0.0`)

### Backend

- Python 3.11+
- FastAPI + Uvicorn
- OpenCV (`opencv-python-headless`)
- NumPy
- RapidOCR (`rapidocr-onnxruntime`) — OCR liviano, CPU
- RapidFuzz — matching de nombres
- Pillow
- Pydantic v2
- Puerto **43124** (`0.0.0.0`)

### Comunicación

- UI llama al backend en `http://127.0.0.1:43124`.
- Next.js: rewrite opcional `/backend/*` → FastAPI, **o** `NEXT_PUBLIC_API_URL=http://127.0.0.1:43124`.
- Jobs largos: **SSE** (`GET /jobs/{id}/events`) para la barra de progreso. Polling `GET /jobs/{id}` como fallback.

### Muestreo

- **1 FPS** de análisis (1 frame de video por segundo de tiempo de partido).
- Extraer con OpenCV (`cap.set(CAP_PROP_POS_MSEC, ...)`), no decodificar todos los frames.

---

## 5. Principio de ROI LED (el corazón del sistema)

```
[ marcador broadcast — IGNORAR ]
[ gradas azules — IGNORAR ]
[ lonas fijas "NETTPLUS / MACON / CAMERO" — IGNORAR ]
[ ============ VALLA LED (única zona OCR) ============ ]
[ césped verde ======================================== ]
```

Pasos, en este orden:

1. Detectar césped por color HSV.
2. En cada columna `x`, el **primer píxel verde desde arriba dentro de la mitad inferior-media** (o el borde superior del mayor blob de grama) es la **línea de cal**.
3. La LED es la franja **inmediatamente encima** de esa línea, de altura fija pequeña.
4. **Nunca** extender el recorte hacia arriba lo suficiente como para comerse las lonas.
5. OCR **solo** sobre ese recorte. El marcador de goles se lee en **otro crop** (esquina superior izquierda), nunca mezclado con la LED.

Altura de la franja LED (1080p de referencia, escalar por `H`):

```python
led_h = int(np.clip(0.055 * frame_h, 28, 90))
```

Margen: 2 px por encima del césped para no meter grama en el OCR.

---

## 6. Arquitectura

```
Browser (Next.js :43123)
    │  POST /jobs  (multipart: videos + brands JSON + logos)
    │  GET  /jobs/{id}           estado + resultado
    │  GET  /jobs/{id}/events    SSE progreso
    ▼
FastAPI (:43124)
    │  JobManager (dict in-memory + carpeta data/jobs/{id}/)
    ▼
Pipeline (un thread/async worker por job)
    1. scoreboard   → t0 de 1T y (si aplica) t0 de 2T
    2. sampler      → frames a 1 FPS desde t0, hasta duration
    3. camera_gate  → ¿es plano lateral? si no, skip
    4. roi_led      → crop de la franja LED
    5. ocr_brands   → texto + fuzzy match contra lista del usuario
    6. hysteresis   → rellena 1s huecos
    7. aggregate    → apariciones, duraciones, start_frames
```

Sin GPU. Un job a la vez está bien en v1 (cola de 1). Si llega otro, HTTP 409 o encolarlo y procesar en serie.

---

## 7. Modelo de datos

### Marca de entrada

```json
{
  "id": "nettplus",
  "name": "NETT plus",
  "aliases": ["NETTPLUS", "NET PLUS", "NETPLUS", "NETT PLUS"]
}
```

- `id`: slug generado del nombre.
- `name`: como lo escribió el usuario.
- `aliases`: usuario puede mandarlos; **siempre** autogenerar variantes (quitar espacios, `+` ↔ `plus`, mayúsculas, sin tildes).
- Logo: archivo opcional `logo_{id}.png` guardado en el job. En v1 el logo **no es necesario para detectar**. Si está, puedes usarlo solo como señal extra (template match débil). Si no estás seguro, **ignóralo**. El nombre basta.

### Resultado por marca

```json
{
  "brand_id": "nettplus",
  "name": "NETT plus",
  "appearances": 3,
  "total_seconds": 47,
  "minutes": 0,
  "seconds": 47,
  "start_frames": [4920, 8104, 15030],
  "segments": [
    {
      "half": "1T",
      "clock_start": "03:25",
      "clock_end": "03:41",
      "video_seconds_start": 205.0,
      "video_seconds_end": 221.0,
      "start_frame": 4920,
      "end_frame": 5400,
      "duration_seconds": 16
    }
  ]
}
```

`start_frames` son los **índices de frame del archivo de video original** (no del muestreo a 1 FPS), al **inicio** de cada segmento.

`minutes` / `seconds` son el total de exposición: `minutes = total_seconds // 60`, `seconds = total_seconds % 60`. Muestra también un texto `mm:ss`.

### Job

```json
{
  "id": "uuid",
  "status": "queued | detecting_kickoff | processing | completed | error",
  "progress": 0.0,
  "progress_label": "1T 03:12 — leyendo valla LED",
  "error": null,
  "config": {
    "mode": "single | split",
    "duration_mode": "5min | 10min | full",
    "sample_fps": 1
  },
  "kickoff": {
    "first_half_video_seconds": 12.4,
    "second_half_video_seconds": 2880.0,
    "note": "detectado por marcador / fallback t=0"
  },
  "result": {
    "analyzed_seconds": 300,
    "brands": []
  }
}
```

---

## 8. Contratos API

Base: `http://127.0.0.1:43124`

### `POST /jobs`

`multipart/form-data`:

- `mode`: `single` | `split`
- `duration_mode`: `5min` | `10min` | `full`
- `brands`: JSON string del array de marcas
- `video` : archivo (si `single`)
- `video_first` / `video_second`: archivos (si `split`)
- `logo_{brand_id}`: opcional, uno por marca

Respuesta `201`: `{ "id": "...", "status": "queued" }`

### `GET /jobs/{id}`

JSON del job (incluye `result` si `completed`).

### `GET /jobs/{id}/events`

`text/event-stream`. Cada evento:

```json
{
  "status": "processing",
  "progress": 0.42,
  "progress_label": "1T 04:01 (42%)",
  "partial_brands": [
    { "name": "NETT plus", "total_seconds": 12, "appearances": 1 }
  ]
}
```

Emitir al menos cada 1–2 segundos de análisis.

### `GET /health`

`{ "ok": true }`

CORS: permitir `http://127.0.0.1:43123` y `http://localhost:43123`.

---

## 9. Árbol de archivos (crear exactamente esto)

```
/workspace
  PLAN.md                          (ya existe; no lo borres)
  README.md
  .gitignore
  backend/
    requirements.txt
    app/
      __init__.py
      main.py                      # FastAPI, CORS, routes
      schemas.py                   # Pydantic
      jobs.py                      # JobManager + worker
      pipeline/
        __init__.py
        video.py                   # abrir video, frame en t, fps, frame_index
        scoreboard.py              # OCR marcador, kickoff 1T/2T
        roi.py                     # césped HSV + franja LED + gate lateral
        ocr.py                     # RapidOCR sobre crop LED
        brands.py                  # normalizar nombres, fuzzy match
        hysteresis.py              # relleno temporal
        aggregate.py               # segmentos y totales
        run.py                     # orquesta un job
  frontend/                        # Next.js app
    src/app/page.tsx
    src/app/layout.tsx
    src/components/...
    src/lib/api.ts
  data/jobs/                       # gitignored
```

No monorepo extra, no packages/, no turbo.

---

## 10. Algoritmos (implementar tal cual)

### 10.1 Extraer frame a tiempo t

```python
def read_frame_at_seconds(cap, t: float):
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
    ok, frame = cap.read()
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_idx = int(round(t * fps))
    return ok, frame, frame_idx
```

### 10.2 Marcador (esquina superior izquierda)

Crop fijo relativo:

```python
h, w = frame.shape[:2]
crop = frame[0:int(0.22 * h), 0:int(0.42 * w)]
```

OCR ese crop. Parsear:

- Reloj: `\b(\d{1,2}):(\d{2})\b` → `mm * 60 + ss`. Ignorar valores `ss > 59`.
- Tiempo: `\b(1T|2T)\b` (también `PT`→1T, `ST`→2T si aparece).

**Kickoff 1T**

Recorrer el video a **0.5–1 FPS** solo el marcador (barato) desde t=0 hasta ~15 min de archivo:

- Primer instante donde hay reloj `<= 8` segundos y (etiqueta 1T **o** aún no vimos 2T).
- Si no hay reloj en 2 minutos de archivo: `first_half_video_seconds = 0` y `note = "fallback t=0"`.

**Kickoff 2T (solo modo** `single`**)**

Después de haber visto un reloj de 1T >= 40:00 **o** la etiqueta 1T durante un rato:

- Primer instante posterior con etiqueta 2T y reloj `<= 8`, **o**
- El reloj **baja de forma brusca** (ej. 45:xx → 00:0x) tras haber superado 40 minutos.

Modo `split`: el segundo archivo es 2T. Detectar kickoff **dentro de cada archivo** igual (saltar previa / entretiempo). No busques 2T dentro del archivo de 1T.

### 10.3 Gate de cámara lateral

Descartar el frame (no OCR de marcas) si:

1. Máscara de césped < 12% de los píxeles, o
2. El borde superior medio del césped está en el **tercio superior** del frame (plano a campo largo / posible fondo de arco), o
3. La altura estimada de la banda LED en px < 22 (valla lejana detrás del arco).

Esos frames **no** cuentan como “la marca no estaba”; son `skipped`. No rompen un segmento si el skip dura ≤ 2s (hysteresis). Si skip > 2s, cierra el segmento.

### 10.4 Césped HSV + línea de cal

```python
hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
# H 35-90 cubre césped día/noche broadcast; afinar si hace falta
lower = np.array([35, 40, 40])
upper = np.array([90, 255, 255])
mask = cv2.inRange(hsv, lower, upper)
mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
```

Para cada `x` en pasos de 4 px, buscar de **abajo hacia arriba** el último (más alto) píxel verde en esa columna, restringido a `y` en `[int(0.28*H), int(0.92*H)]`. Eso da `y_grass[x]`.

Suavizar `y_grass` con mediana de ventana 21.

Si hay pocos puntos válidos, frame skip.

### 10.5 Recorte LED

```python
led_h = int(np.clip(0.055 * H, 28, 90))
# Para cada x: filas [y_grass[x] - led_h, y_grass[x] - 2)
```

Construir una **máscara poligonal** de esa banda y `cv2.bitwise_and`. Luego recortar el bbox de la máscara. Ese crop va a OCR.

**Prohibido:** usar de ROI un rectángulo fijo tipo “el 20% inferior del frame” (se come lonas o se come césped según el zoom).

**Prohibido:** OCR del frame entero.

### 10.6 OCR + match de marcas

- RapidOCR sobre el crop LED (y opcionalmente una versión `cv2.resize` 1.5× si el crop es chico).
- Concatenar todas las cajas de texto en un string `raw`.
- Normalizar:

```python
def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.upper()
    s = s.replace("&", " AND ")
    s = s.replace("+", " PLUS ")
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s
```

- Una marca está presente si:
  - su `norm(name)` o algún alias está **contenido** en `norm(raw)`, o
  - `rapidfuzz.partial_ratio(norm(name), norm(raw)) >= 82`, o
  - `token_set_ratio >= 80` y el nombre tiene ≥ 4 caracteres.

Cuidado: “NETT plus” no debe matchear un recorte que solo dice “LIONS SPORTS AND MEDIA”. Con ROI correcto, “NETTPLUS” de la lona **no entra** al string. No bajes el umbral para “arreglar” falsos negativos si el crop incluye lonas.

Un frame puede tener **varias** marcas si la LED muestra un loop con 2 marcas visibles a la vez (repetidas a lo largo). Eso es válido.

### 10.7 Hysteresis (suavizado temporal)

Serie a 1 Hz: para cada marca, vector booleano por segundo analizado (`skipped` no es False: es “no opinar”).

```
Si True en t-1 y True en t+1 y (t skipped o False): forzar True en t.
Cerrar segmento tras 2 False consecutivos (no skipped).
Skipped de 1s no cierra; skipped de 3s+ cierra.
```

Esto cubre el ejemplo: OCR falla 1 segundo en un paneo.

### 10.8 Duración a analizar

Sea `t0` el kickoff de esa mitad (segundos de archivo).

| `duration_mode` | Ventana                                                                       |
| --------------- | ----------------------------------------------------------------------------- |
| `5min`          | `[t0, t0+300)`                                                                |
| `10min`         | `[t0, t0+600)`                                                                |
| `full`          | desde `t0` hasta fin de archivo (o hasta que desaparezca el reloj mucho rato) |

Modo `split` + `5min` / `10min`: **solo** el primer tiempo.

Modo `split` + `full`: 1T completo + 2T completo (cada uno desde su kickoff).

Modo `single` + `full`: 1T desde kickoff 1T hasta kickoff 2T (o 45:00+descuento si no detectas 2T), luego 2T desde su kickoff al final.

No analices previa, himno, ni entretiempo si detectaste t0.

### 10.9 Segundos totales

Con 1 FPS y hysteresis ya aplicado:

`total_seconds = cantidad de samples True`

No dividas por el FPS del MP4. El FPS de **análisis** es 1.

`start_frame` del segmento = `frame_idx` del primer sample True de ese tramo.

---

## 11. Interfaz (español, copy real)

Una sola página. Desktop y móvil.

### Estados

- **Vacío:** aún no hay job. Mensaje: “Subí el video del partido y la lista de marcas. Solo medimos la valla LED a ras de césped, no las lonas fijas ni los fondos de arco.”
- **Listo para analizar:** video(s) + al menos 1 marca.
- **Procesando:** barra `Progress` de shadcn + `progress_label` + tabla parcial.
- **Error:** texto del backend + botón “Volver a intentar”.
- **Completado:** tabla final + resumen “Analizamos X min de 1T…”

### Bloques de UI

1. **Video**

- Tabs: “Un video (partido completo)” | “Dos videos (1T y 2T)”
- Dropzone(s) que aceptan mp4/mov/mkv/webm
- Nombre del archivo y tamaño cuando está cargado

2. **Marcas**

- Input nombre + botón “Agregar”
- Lista: chip con nombre, botón quitar, input file “Logo (opcional)”
- Placeholder del input: “Ej. NETT plus”

3. **Ventana de análisis**

- Select: `5 minutos` / `10 minutos` / `Partido entero`
- Texto de ayuda: “Arranca en el saque inicial que leemos del marcador (arriba a la izquierda). Útil para pruebas cortas.”

4. **Botón** “Analizar vallas LED” (disabled si falta video o marcas)
5. **Progreso** (visible en processing): porcentaje + label
6. **Resultados** tabla:

| Marca     | Apariciones | Tiempo     | Frames de inicio |
| --------- | ----------- | ---------- | ---------------- |
| NETT plus | 2           | 0 min 18 s | 4920, 8104       |

Si una marca no apareció: 0, 0 min 0 s, “—”. No la ocultes.

Estética: fondo oscuro tipo broadcast, acento verde césped / amarillo marcador. Tipografía clara. Nada de lorem, nada de “Welcome to your app”.

---

## 12. Fases de implementación

Hacé **commit + push al final de cada fase**. No saltees fases.

### Fase 0 — Scaffold

**Frontend** (el parent de `frontend/` es `/workspace`, eso es correcto; **no** corras `create-next-app` sobre `/workspace` ni `.`):

```bash
cd /workspace
npx create-next-app@latest frontend --typescript --tailwind --eslint --app --src-dir --import-alias "@/*" --use-npm --yes
```

Luego shadcn init (defaults, dark) y los componentes listados en §4.

`package.json` script:

```json
"dev": "next dev -H 0.0.0.0 -p 43123"
```

**Backend:**

```bash
mkdir -p /workspace/backend/app/pipeline
python3 -m venv /workspace/backend/.venv
source /workspace/backend/.venv/bin/activate
pip install fastapi "uvicorn[standard]" python-multipart opencv-python-headless numpy rapidocr-onnxruntime rapidfuzz pillow pydantic
pip freeze > /workspace/backend/requirements.txt
```

`.gitignore`: `node_modules`, `.next`, `.venv`, `__pycache__`, `data/jobs`, `.env`, `*.mp4`.

`README.md` mínimo (se completa en fase 8).

Levantar backend:

```bash
cd /workspace/backend && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 43124
```

`GET /health` debe responder.

### Fase 1 — UI shell (sin análisis real)

Pantalla completa de §11 con estado local:

- tabs de video, dropzones, lista de marcas, select de duración, botón.
- Estados vacío / listo.
- No hace falta que el botón procese de verdad todavía; puede quedar disabled con tooltip “backend en la siguiente fase” **o** ya apuntar al API (mejor si Fase 2 está en el mismo día).

### Fase 2 — Jobs + progreso fake

- `POST /jobs` guarda archivos en `data/jobs/{id}/`.
- Worker dummy: 5 segundos emitiendo progreso 0→100 por SSE.
- UI: al submit, barra de progreso real contra SSE.
- Al completar, mostrar tabla dummy de 1 marca para verificar el layout de resultados.

### Fase 3 — Video + marcador + kickoff

Implementar `video.py` + `scoreboard.py`.

Endpoint interno o campo `kickoff` en el job real:

- Loguear t0 1T y t0 2T.
- UI: en `detecting_kickoff` mostrar “Buscando el saque inicial en el marcador…”.

Probar con cualquier MP4 corto si no hay partido. Si no hay marcador, fallback t=0.

### Fase 4 — ROI LED + gate

`roi.py` debe devolver:

```python
@dataclass
class RoiResult:
    skipped: bool
    reason: str | None
    crop_bgr: np.ndarray | None   # solo LED
    debug_overlay: np.ndarray | None  # opcional: línea de cal dibujada
```

Guardar 1 de cada 30 crops en `data/jobs/{id}/debug/` para inspección. **El crop no debe mostrar las lonas “MACON / CAMERO / NETTPLUS fijas”.** Si las muestra, bajá `led_h`.

### Fase 5 — OCR + marcas

`ocr.py` + `brands.py`. Un frame → set de `brand_id` presentes.

Incluí aliases fuertes para el ejemplo:

- NETT plus → NETTPLUS, NETPLUS, NET PLUS, NETT PLUS
- Lions Sports & Media → LIONS SPORTS AND MEDIA, LIONS SPORT AND MEDIA, LIONS SPORTS MEDIA

### Fase 6 — Hysteresis + agregación + job real

Reemplazar el worker dummy. El job recorre `[t0, t0+window)` a 1 FPS, actualiza SSE, escribe `result`.

### Fase 7 — UI final

Conectar todo. Tabla real. Marcas en 0 visibles. Errores de upload (archivo no video, job en curso).

Durante processing no se debe poder lanzar otro job (disable).

### Fase 8 — README, verificación, polish

README con:

- qué es
- cómo diferenciar LED vs lona (una frase)
- requisitos (Python 3.11, Node 20)
- `backend/.venv` + `uvicorn ... --port 43124`
- `cd frontend && npm run dev`
- variables `NEXT_PUBLIC_API_URL`
- limitaciones v1 (laterales, 1 FPS, CPU, OCR puede fallar en paneos fuertes)

Verificar en el navegador el flujo completo con un video de prueba (aunque sea 15s). Si no hay partido real, usá un mp4 cualquiera y confirmá: upload → progreso → tabla (ceros).

---

## 13. Criterios de aceptación

- [ ] Se puede subir 1 video o 1T+2T.
- [ ] Lista de marcas por nombre; logo opcional y no bloquea.
- [ ] Select 5 min / 10 min / partido entero.
- [ ] Barra de progreso con porcentaje y texto (mitad + reloj si se conoce).
- [ ] Resultado: apariciones, minutos, segundos, frames de inicio.
- [ ] OCR **solo** sobre la franja LED a ras de césped.
- [ ] Caso canónico: a 03:25 cuenta NETT plus; a 03:27 cuenta Lions y **no** NETT plus por la lona.
- [ ] No cuenta fondos de arco (gate de cámara).
- [ ] 1 FPS + hysteresis de 1s.
- [ ] Kickoff leído del marcador; fallback t=0 con nota.
- [ ] UI en español, vacío / loading / error / éxito.
- [ ] Desktop y móvil usables.
- [ ] README para correr local.

---

## 14. Comandos de verificación

```bash
curl -s http://127.0.0.1:43124/health
# frontend
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:43123
```

Job mínimo (cuando tengas un mp4):

```bash
curl -F mode=single -F duration_mode=5min \
  -F 'brands=[{"name":"NETT plus","aliases":["NETTPLUS","NETPLUS"]}]' \
  -F video=@/path/to/clip.mp4 \
  http://127.0.0.1:43124/jobs
```

---

## 15. Decisiones que ya están tomadas (no reabrir)

| Tema                        | Decisión                          |
| --------------------------- | --------------------------------- |
| YOLO / SAM / entrenar logos | No en v1                          |
| OCR                         | RapidOCR CPU sobre crop LED       |
| FPS análisis                | 1                                 |
| Detrás del arco             | No se cuenta                      |
| Lonas fijas                 | No se cuentan (ROI geométrica)    |
| Logo del usuario            | Opcional, ignorar si no aporta    |
| DB                          | No; disco + memoria               |
| Cola distribuida            | No                                |
| Puertos                     | 43123 UI, 43124 API               |
| UI                          | Next + Tailwind + shadcn, español |

---

## 16. Orden de commits sugerido

1. `chore: scaffold frontend Next.js and FastAPI backend`
2. `feat: upload UI for videos, brands and analysis window`
3. `feat: job API with SSE progress`
4. `feat: detect kickoff from broadcast scoreboard`
5. `feat: isolate sideline LED ROI from grass edge`
6. `feat: OCR brand matching on LED crop`
7. `feat: temporal aggregation and results table`
8. `docs: README and run instructions`

---

## 17. Si te trabás

- **create-next-app dice que el path no es writable:** estás apuntando a `/workspace`. Usá `/workspace/frontend`.
- **OCR no lee la LED:** agrandá el crop 1.5×, no agrandes `led_h` por encima de 90 px (vas a comer lonas).
- **NETT plus aparece cuando la LED dice Lions:** el crop incluye lonas. Dibujá `debug_overlay` y recortá más bajo.
- **PaddleOCR / EasyOCR / torch:** no. RapidOCR onnx.
- **“Mejor entreno YOLO”:** no. Fuera de alcance.
- **No hay video de partido en el entorno:** implementá igual; verificá health, UI y un mp4 corto sintético.
