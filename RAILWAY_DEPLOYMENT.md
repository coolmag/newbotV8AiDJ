# Деплой DJ Aurora на Railway.app

## 🚀 Быстрая настройка (5 минут)

### 1. Подготовка репозитория
```bash
git clone https://github.com/coolmag/newbotV8AiDJ.git
cd newbotV8AiDJ-main
```

### 2. Установка Railway CLI
```bash
# macOS
brew install railway

# Windows (PowerShell)
iwr -useb https://railway.app/install.ps1 | iex

# Linux
curl -fsSL https://railway.app/install.sh | sh
```

### 3. Авторизация и создание проекта
```bash
railway login
railway init
```

### 4. Настройка переменных окружения

Создайте файл `railway.toml` в корне проекта:
```toml
[build]
builder = "nixpacks"
buildCommand = "pip install -r requirements.txt"

[deploy]
startCommand = "python main.py"

[[variables]]
key = "PORT"
value = "8000"

[[variables]]
key = "TELEGRAM_TOKEN"
value = "ВАШ_BOT_TOKEN"

[[variables]]
key = "ADMIN_USER_IDS"
value = "ВАШ_TELEGRAM_ID"

[[variables]]
key = "CLOUDFLARE_ACCOUNT_ID"
value = "ВАШ_CLOUDFLARE_ACCOUNT_ID"

[[variables]]
key = "CLOUDFLARE_API_TOKEN"
value = "ВАШ_CLOUDFLARE_API_TOKEN"
```

### 5. Деплой
```bash
railway up
```

## ⚙️ Настройка переменных в Railway Dashboard

1. Перейдите на https://railway.app/dashboard
2. Выберите ваш проект
3. Перейдите в `Settings` → `Variables`
4. Добавьте следующие переменные:

### Обязательные переменные:
```env
PORT=8000
TELEGRAM_TOKEN=ваш_токен_бота
ADMIN_USER_IDS=ваш_telegram_id
```

### AI провайдеры (рекомендуется Cloudflare):
```env
# Cloudflare (бесплатно, 100K запросов/день)
CLOUDFLARE_ACCOUNT_ID=your_account_id_here
CLOUDFLARE_API_TOKEN=your_api_token_here

# Groq (бесплатный tier)
GROQ_API_KEY=gsk_your_key_here

# Gemini (бесплатный tier)
GEMINI_API_KEY=your_gemini_key_here
GEMINI_API_KEYS=key1,key2,key3
```

### Опциональные переменные:
```env
# Redis для кэширования (рекомендуется)
REDIS_URL=redis://...

# Логирование
LOG_LEVEL=INFO
```

## 🔧 Проверка работоспособности

После деплоя:

### 1. Проверка логов
```bash
railway logs
```

### 2. Проверка здоровья API
```bash
curl https://ваш-проект.railway.app/api/health
```

### 3. Проверка бота в Telegram
Отправьте команды:
- `/start` - приветствие
- `/status` - проверка системы
- `/test_ai` - тестирование AI

## 📊 Мониторинг

Railway предоставляет:
- **Логи в реальном времени**
- **Метрики использования CPU/памяти**
- **Мониторинг сети**
- **Автоматическое масштабирование**

## 🔄 Обновление бота

### Вариант 1: Через Railway CLI
```bash
git push railway main
```

### Вариант 2: Через GitHub
1. Подключите GitHub репозиторий в Railway Dashboard
2. Railway автоматически деплоит при пуше в ветку

### Вариант 3: Вручную
```bash
railway run python main.py
```

## 🛠️ Устранение неполадок

### Проблема: Бот не запускается
```bash
# Проверьте логи
railway logs --tail

# Проверьте переменные
railway vars list
```

### Проблема: AI не отвечает
1. Проверьте команду `/status`
2. Убедитесь что API ключи правильно установлены
3. Проверьте `test_ai_providers.py` локально

### Проблема: Ошибка порта
Убедитесь что в Railway установлено:
```env
PORT=8000
```

### Проблема: YouTube блокирует запросы
Бот использует yt-dlp, который автоматически обновляет cookies.

## 📈 Оптимизация производительности

### Рекомендуемые настройки Railway:
- **Plan**: Hobby (бесплатно)
- **Autoscale**: включено
- **Min Instances**: 1
- **Max Instances**: 3

### Оптимизация памяти:
Добавьте в `railway.json`:
```json
{
  "build": {
    "nixpacks": {
      "config": {
        "phases": {
          "install": {
            "runtimeEnvVars": {
              "PYTHONUNBUFFERED": "1",
              "PYTHONDONTWRITEBYTECODE": "1"
            }
          }
        }
      }
    }
  }
}
```

## 🔒 Безопасность

### Рекомендации:
1. **Не храните токены в репозитории**
2. **Используйте Railway Secrets для конфиденциальных данных**
3. **Ограничьте доступ к панели администратора**
4. **Регулярно обновляйте зависимости**

### Проверка безопасности:
```bash
pip-audit
safety check
```

## 📊 Логирование

Бот использует структурированное логирование:
- `INFO`: Основные события
- `WARNING`: Предупреждения
- `ERROR`: Критические ошибки
- `DEBUG`: Детальная отладка (включить через `LOG_LEVEL=DEBUG`)

Просмотр логов:
```bash
railway logs --level error
railway logs --tail 100
```

## 🚀 Дополнительные ресурсы

- [Railway документация](https://docs.railway.app/)
- [Cloudflare Workers AI документация](https://developers.cloudflare.com/workers-ai/)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [yt-dlp документация](https://github.com/yt-dlp/yt-dlp)

## 📞 Поддержка

Если возникли проблемы:
1. Проверьте логи: `railway logs`
2. Проверьте переменные: `railway vars list`
3. Запустите тесты: `python test_ai_providers.py`
4. Создайте issue в GitHub репозитории