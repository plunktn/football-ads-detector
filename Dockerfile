FROM python:3.11-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/

RUN mkdir -p data/jobs data/brands

ENV PYTHONUNBUFFERED=1
ENV KEEP_JOB_VIDEOS=false

EXPOSE 8000

CMD sh -c "cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"
