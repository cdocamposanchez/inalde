# ============================================================
# INALDE · Motor de Curaduría Ejecutiva
# ============================================================
FROM python:3.12-slim

# Evita prompts y .pyc; salida sin búfer para ver logs en vivo.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencias del sistema necesarias para psycopg y reportlab.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Instala dependencias de Python primero (mejor cacheo de capas).
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copia el código de la aplicación.
COPY . .

# Carpeta de subidas (hojas de vida en PDF).
RUN mkdir -p /app/uploads

EXPOSE 7070

# Arranque: aplica el esquema, siembra catálogos y levanta el servidor.
CMD ["sh", "-c", "python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port 7070"]
