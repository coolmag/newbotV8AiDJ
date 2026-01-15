FROM python:3.11-slim

# 1. Установка Node.js (критично для YouTube!) и FFmpeg
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Создаем ссылку node -> nodejs (yt-dlp ищет именно "node")
RUN ln -s /usr/bin/nodejs /usr/bin/node || true

WORKDIR /app

# 2. Зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 3. Код
COPY . .

# 4. Запуск
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]