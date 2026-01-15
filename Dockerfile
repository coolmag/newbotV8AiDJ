# Используем легкий образ Python 3.11
FROM python:3.11-slim

# 1. Установка системных зависимостей
# ffmpeg - для аудио
# nodejs - для подписи YouTube (ОБЯЗАТЕЛЬНО)
RUN apt-get update && \
    apt-get install -y ffmpeg nodejs npm && \
    rm -rf /var/lib/apt/lists/*

# Настройка рабочей директории
WORKDIR /app

# 2. Установка Python-библиотек
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. Копирование всего кода проекта
COPY . .

# 4. Команда запуска (использует порт Railway)
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
