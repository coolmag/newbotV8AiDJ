#!/usr/bin/env python3
"""
Тест VK Music Engine
Проверяет корректность миграции с YouTube на VK
"""

import asyncio
import os
import sys
from pathlib import Path

# Добавляем текущую директорию в путь
sys.path.append(str(Path(__file__).parent))

async def test_vk_integration():
    print("🧪 Тестирование VK Music Engine...")
    
    try:
        # Проверяем импорты
        print("📦 Проверка импортов...")
        import vk_api
        import httpx
        print("✅ vk_api, httpx - OK")
        
        # Проверяем наш модуль
        from youtube import YouTubeDownloader
        from config import get_settings
        from cache_service import CacheService
        print("✅ Наши модули - OK")
        
        # Проверяем настройки
        print("⚙️ Проверка настроек...")
        settings = get_settings()
        
        vk_login = os.getenv("VK_LOGIN")
        vk_password = os.getenv("VK_PASSWORD")
        
        if not vk_login or not vk_password:
            print("⚠️ VK_LOGIN и VK_PASSWORD не найдены в переменных окружения")
            print("💡 Для тестирования добавьте их в .env файл или переменные окружения")
            return False
        
        print(f"✅ VK_LOGIN найден: {vk_login}")
        print("✅ VK_PASSWORD найден: [Скрыт]")
        
        # Инициализируем кэш и загрузчик
        print("🔧 Инициализация компонентов...")
        cache = CacheService(settings.CACHE_DB_PATH)
        await cache.initialize()
        
        downloader = YouTubeDownloader(settings, cache)
        
        if not downloader.is_active:
            print("❌ VK авторизация не удалась")
            return False
        
        print("✅ VK Music Engine инициализирован")
        
        # Тест поиска
        print("🔍 Тест поиска...")
        tracks = await downloader.search("русский рок", limit=3)
        
        if not tracks:
            print("❌ Поиск вернул пустой результат")
            return False
        
        print(f"✅ Найдено треков: {len(tracks)}")
        
        for i, track in enumerate(tracks, 1):
            print(f"  {i}. {track.artist} - {track.title} ({track.duration}s)")
        
        # Тест скачивания (первый трек)
        print("⬇️ Тест скачивания...")
        first_track = tracks[0]
        print(f"Скачиваем: {first_track.identifier}")
        
        result = await downloader.download(first_track.identifier, first_track)
        
        if result.success:
            print("✅ Скачивание успешно!")
            if result.file_path:
                print(f"📁 Файл сохранен: {result.file_path}")
            elif result.file_id:
                print(f"📱 File ID получен: {result.file_id[:20]}...")
        else:
            print(f"❌ Ошибка скачивания: {result.error_message}")
            return False
        
        await cache.close()
        print("🎉 Все тесты пройдены успешно!")
        return True
        
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
        print("💡 Установите зависимости: pip install vk_api httpx")
        return False
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_vk_integration())
    sys.exit(0 if success else 1)