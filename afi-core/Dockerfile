FROM python:3.11-slim

# Instalar dependencias de sistema para Audio (ffmpeg) y Gráficos
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libpq-dev \
    gcc \
    postgresql-client \
    rclone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Comando de inicio
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--reload"]
