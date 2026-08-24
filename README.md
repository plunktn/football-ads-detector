# Football Ads Detector

Herramienta local para medir publicidad en las vallas LED laterales de un
partido de fútbol. Las primeras fases incluyen la interfaz de carga, jobs con
progreso SSE y detección del saque inicial desde el marcador.

## Desarrollo

Requisitos: Python 3.11+ y Node.js 20+.

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 43124
```

En otra terminal:

```bash
cd frontend
npm run dev
```

Frontend: http://127.0.0.1:43123 · API: http://127.0.0.1:43124

La API también se puede cambiar con `NEXT_PUBLIC_API_URL`.
