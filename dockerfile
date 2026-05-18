FROM python:3.13-slim

# Instalar ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && apt-get clean

# Carpeta de trabajo
WORKDIR /app

# Copiar requirements
COPY requirements.txt .

# Instalar dependencias Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo el proyecto
COPY . .

# Crear carpeta downloads
RUN mkdir -p downloads

# Puerto Railway
ENV PORT=8000

# Ejecutar FastAPI
CMD uvicorn main:app --host 0.0.0.0 --port $PORT