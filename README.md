# Football Ads Detector

Herramienta local para medir la exposición de marcas en las vallas LED
laterales de un partido de fútbol. Subí un partido completo o los dos
tiempos, cargá la lista de marcas y recibí apariciones, tiempo total y frames
de inicio.

El sistema detecta el césped, toma la franja luminosa inmediatamente encima
de su borde y aplica OCR únicamente allí; las lonas fijas de arriba y los
fondos de arco quedan fuera del análisis.

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

Abrí http://127.0.0.1:43123. La API queda disponible en
http://127.0.0.1:43124 y responde `{ "ok": true }` en `/health`.

Si necesitás otra dirección para la API, definí:

```bash
NEXT_PUBLIC_API_URL=http://127.0.0.1:43124
```

## Uso

1. Elegí un video completo o cargá 1T y 2T.
2. Agregá al menos una marca; el logo es opcional y no bloquea el OCR.
3. Elegí 5 minutos, 10 minutos o partido entero.
4. Presioná **Analizar vallas LED** y seguí el progreso por SSE.

El análisis busca el saque inicial en el marcador superior izquierdo y usa
`t=0` como fallback cuando no puede leerlo. Los crops y overlays de depuración
se guardan en `backend/data/jobs/{id}/debug/`; el resultado final queda en
`result.json`.

## Limitaciones v1

- Solo vallas laterales; no se cuentan fondos de arco ni lonas fijas.
- Muestreo de análisis a 1 FPS, aunque el MP4 tenga 30/60 FPS.
- Procesamiento local en CPU; paneos fuertes, blur o tipografías pequeñas
  pueden hacer fallar el OCR.
- No se entrenan modelos custom ni se detectan marcas que no fueron cargadas.

## Verificación

```bash
cd backend
.venv/bin/python -m unittest discover -s tests -v
cd ../frontend
npm run lint
npm run build
```
