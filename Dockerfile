FROM python:3.11-slim

WORKDIR /app

# Устанавливаем FFmpeg и другие зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*
RUN node -v

# Копируем requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir --upgrade yt-dlp

# Копируем код
COPY . .

# Создаём директории
RUN mkdir -p downloads temp_audio

# Запуск
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
