# DJ Aurora - AI Music Telegram Bot

Бот для Telegram с AI-ассистентом и радио-функциями. Ищет музыку на YouTube, генерирует плейлисты с помощью AI и проигрывает их.

## 🚀 Быстрый старт

### 1. Клонирование и установка
```bash
git clone https://github.com/coolmag/newbotV8AiDJ.git
cd newbotV8AiDJ-main
pip install -r requirements.txt
```

### 2. Настройка переменных окружения
Создайте файл `.env` на основе `.env.example`:

```bash
# Основные настройки
TELEGRAM_TOKEN=your_bot_token_here
ADMIN_USER_IDS=your_telegram_id

# AI провайдеры (РЕКОМЕНДУЕМЫЙ - Cloudflare)
CLOUDFLARE_ACCOUNT_ID=your_account_id
CLOUDFLARE_API_TOKEN=your_api_token

# Альтернативные AI провайдеры
GROQ_API_KEY=your_groq_key_here
OPENROUTER_API_KEY=your_openrouter_key_here
DEEPSEEK_API_KEY=your_deepseek_key_here
GEMINI_API_KEY=your_gemini_key_here
```

### 3. Получение API ключей

#### Cloudflare Workers AI (БЕСПЛАТНЫЙ - РЕКОМЕНДУЕМЫЙ)
1. Зарегистрируйтесь на https://dash.cloudflare.com/
2. Найдите Account ID в профиле → API Tokens
3. Создайте API Token с разрешениями "Workers AI:Edit"
4. Подробная инструкция: [CLOUDFLARE_SETUP.md](./CLOUDFLARE_SETUP.md)

#### Groq API (бесплатный, быстрый)
1. Перейдите на https://console.groq.com/keys
2. Создайте новый API ключ
3. Скопируйте ключ (начинается с `gsk_`)

#### Gemini API (Google AI)
1. Перейдите на https://aistudio.google.com/app/apikey
2. Создайте новый API ключ
3. Добавьте в `GEMINI_API_KEY`

### 4. Запуск бота
```bash
python main.py
```

Или через Docker:
```bash
docker build -t dj-aurora .
docker run -p 8000:8000 dj-aurora
```

## 🤖 AI Провайдеры

Бот поддерживает каскадную систему AI провайдеров:

### Приоритет использования:
1. **Cloudflare Workers AI** - 100K запросов/день бесплатно
2. **Groq** - бесплатный tier, очень быстрый
3. **OpenRouter** - бесплатные кредиты
4. **Gemini** - fallback

### Проверка работы AI
```bash
python test_ai_providers.py
```

Команды в боте:
- `/status` - показывает активные провайдеры
- `/test_ai` - тестирует все AI провайдеры

## 🎵 Функционал

### AI Режимы:
- `default` - весёлая DJ Aurora
- `toxic` - саркастичная версия
- `quiz` - музыкальная викторина
- `chill` - ночной режим
- `gop` - уличный стиль

### Команды:
- `/admin` - панель управления режимами
- `/play <запрос>` - поиск и воспроизведение
- `/radio <тема>` - создание радио-волны
- `/stop` - остановка воспроизведения
- `/status` - статус системы

### Веб-интерфейс
Бот также предоставляет веб-панель на порту 8000 с:
- Плеером музыки
- AI-ассистентом
- Управлением радио

## 🏗️ Архитектура

```
.
├── main.py              # Основное приложение
├── ai_config.py         # Конфигурация AI провайдеров
├── ai_manager.py        # Управление AI запросами
├── ai_personas.py       # Персонажи бота
├── chat_service.py      # Чат-сервис с кэшированием
├── nlp.py              # Обработка естественного языка
├── radio.py            # Радио-функционал
├── youtube.py          # YouTube интеграция
├── handlers.py         # Обработчики команд Telegram
├── webapp/            # Веб-интерфейс
│   ├── js/api.js      # API фронтенда
│   └── js/main.js     # Основная логика фронтенда
└── test_*.py          # Тесты
```

## 📊 Мониторинг и логи

Бот использует структурированное логирование:
- Все AI запросы логируются
- Ошибки API обрабатываются с классификацией
- Состояние кэшируется для скорости

## 🚀 Деплой на Railway

1. Создайте проект на Railway.app
2. Подключите GitHub репозиторий
3. Добавьте переменные окружения в Railway dashboard
4. Railway автоматически развернёт бота

**Рекомендуемые переменные для Railway:**
- `PORT=8000`
- `TELEGRAM_TOKEN`
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_API_TOKEN`

## 🔧 Технические детали

### Обработка ошибок API
- Структурированные ошибки с классификацией
- Автоматический fallback на другой провайдер
- Кэширование успешных ответов

### Кэширование
- Кэш AI ответов в Redis (если настроен)
- Кэш YouTube запросов
- Session-кэш для пользователей

### Масштабирование
- Асинхронная архитектура
- Connection pooling для AI API
- Rate limiting для провайдеров

## 🐛 Отладка

### Логирование
```python
python main.py --log-level DEBUG
```

### Тестирование
```bash
python test_ai_providers.py        # Проверка AI провайдеров
python test_main_ai.py            # Тест основной AI логики
python test_nlp.py                # Тест NLP обработки
```

### Проверка здоровья
```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/player/status
```

## 📈 Производительность

### Оптимизации:
- Кэширование AI ответов
- Предварительная загрузка музыки
- Асинхронные HTTP запросы
- Connection pooling

### Мониторинг:
- `/status` команда в боте
- Логи в реальном времени
- Метрики ответов API

## 🤝 Вклад в проект

1. Форкните репозиторий
2. Создайте ветку для фичи
3. Добавьте тесты
4. Сделайте Pull Request

## 📄 Лицензия

MIT License - смотрите файл LICENSE