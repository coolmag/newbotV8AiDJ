# 🎵 Миграция на VK Music Engine - Инструкция

## ✅ Что сделано

1. **Обновлён requirements.txt** - убрали yt-dlp, ytmusicapi, добавили vk_api, httpx
2. **Переписан youtube.py** - теперь использует VK Music API (Kate Mobile протокол)
3. **Обновлена конфигурация** - добавлены переменные VK_LOGIN и VK_PASSWORD
4. **Сохранена совместимость** - остальной код не требует изменений

## 🚀 Что нужно сделать

### 1. Установить зависимости

```bash
pip install vk_api>=11.9.9 httpx beautifulsoup4
```

### 2. Настроить переменные окружения

**Для Railway:**
- Откройте настройки проекта на Railway
- Добавьте переменные:
  - `VK_LOGIN`: Ваш номер телефона (например, +79001234567)
  - `VK_PASSWORD`: Пароль от аккаунта ВК

**Для локального запуска:**
Создайте файл `.env` или добавьте в существующий:
```env
VK_LOGIN=+79001234567
VK_PASSWORD=your_password_here
```

### 3. Рекомендации по безопасности

- **Используйте отдельный аккаунт** - не основной, а дополнительный для бота
- **Не используйте 2FA** - если есть двухфакторная аутентификация, временно отключите её
- **Пароль должен быть простым** - без спецсимволов, которые могут вызвать проблемы с экранированием

## 🔧 Как это работает

### Архитектура "Adapter"

```python
class YouTubeDownloader:
    # Внешне выглядит как старый YouTubeDownloader
    # Но внутри работает с VK Music API
```

### Процесс работы

1. **Поиск:** `vk_audio.search(query)` → парсим результаты
2. **Скачивание:** Получаем прямую ссылку на MP3 → качаем через httpx
3. **Кэширование:** Сохраняем file_id в Telegram для повторного использования

### Преимущества VK над YouTube

- **✅ Прямые ссылки:** ВК отдает прямые ссылки на MP3
- **✅ Лояльные IP:** Railway/DigitalOcean не блокируются
- **✅ Мягкие лимиты:** Можно качать быстрее и больше
- **✅ Стабильные API:** Не нужно бороться с антиботом

## 🧪 Тестирование

### Проверка авторизации

```python
import os
from youtube import YouTubeDownloader
from config import get_settings
from cache_service import CacheService

settings = get_settings()
cache = CacheService(settings.CACHE_DB_PATH)
downloader = YouTubeDownloader(settings, cache)

# Должно показать: "✅ VK Music Engine: ONLINE (Kate Mobile Protocol)"
```

### Тест поиска

```python
tracks = await downloader.search("русский рок", limit=5)
print(f"Найдено треков: {len(tracks)}")
for track in tracks:
    print(f"- {track.artist}: {track.title}")
```

## 🐛 Возможные проблемы

### 1. Ошибка авторизации
```
❌ VK Auth Error: AuthError: Bad password
```
**Решение:** Проверьте логин/пароль, временно отключите 2FA

### 2. Капча
```
❌ VK Auth Error: Captcha required
```
**Решение:** Используйте отдельный аккаунт, избегайте частых логинов

### 3. Пустой поиск
```
VK Search API Error: ...
```
**Решение:** Проверьте интернет-соединение, попробуйте перелогиниться

## 📊 Мониторинг

Логи теперь показывают:
- `[VK] Cache HIT (Telegram ID)` - файл уже есть в Telegram
- `[VK] Cache HIT (File)` - файл есть на диске  
- `[VK] Downloading: ...` - скачиваем новый трек
- `[VK] Download Success` - успешно скачали

## 🔄 Rollback (если нужно)

Если что-то пойдет не так:

1. Откатите `youtube.py` к старой версии
2. Верните `yt-dlp` и `ytmusicapi` в requirements.txt
3. Удалите VK переменные из окружения

---

**💡 Фишка:** Эта миграция - пример паттерна "Adapter". Мы не ломаем существующий код, а просто меняем внутренний движок под VK API, сохраняя тот же интерфейс.