#!/usr/bin/env python3
"""
Тест VK Music Engine с защитными механизмами
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

async def test_vk_engine():
    print("🧪 Тестирование VK Music Engine...")
    
    # Проверка переменных окружения
    vk_login = os.getenv("VK_LOGIN")
    vk_password = os.getenv("VK_PASSWORD")
    
    if not vk_login or not vk_password:
        print("⚠️ Добавь VK_LOGIN и VK_PASSWORD в .env")
        print("💡 Пример:")
        print("   VK_LOGIN=+79001234567")
        print("   VK_PASSWORD=мой_пароль")
        return False
    
    try:
        from youtube import YouTubeDownloader
        from config import get_settings
        from cache_service import CacheService
        
        settings = get_settings()
        cache = CacheService(settings.CACHE_DB_PATH)
        await cache.initialize()
        
        downloader = YouTubeDownloader(settings, cache)
        
        if not downloader.is_active:
            print("❌ VK авторизация не удалась")
            return False
        
        print("✅ VK Engine ONLINE")
        
        # Тест поиска
        print("🔍 Тест поиска...")
        tracks = await downloader.search("AC/DC", limit=3)
        
        if not tracks:
            print("❌ Поиск пустой")
            return False
        
        print(f"✅ Найдено: {len(tracks)} треков")
        
        # Тест скачивания
        print("⬇️ Тест скачивания...")
        first = tracks[0]
        result = await downloader.download(first.identifier, first)
        
        if result.success:
            print("✅ Скачивание OK")
            print(f"📁 Файл: {result.file_path}")
        else:
            print(f"❌ Ошибка: {result.error_message}")
            return False
        
        await cache.close()
        print("🎉 Тест пройден!")
        return True
        
    except ImportError as e:
        print(f"❌ Установи зависимости: pip install vk_api httpx")
        print(f"   Ошибка: {e}")
        return False
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_vk_engine())
    sys.exit(0 if success else 1)