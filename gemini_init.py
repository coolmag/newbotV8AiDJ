import os
import logging

# Настраиваем логгер
logger = logging.getLogger("gemini")

HAS_GENAI = False
client = None # Теперь это объект клиента, а не модуль

try:
    # НОВЫЙ ИМПОРТ (Google GenAI SDK v1.0+)
    from google import genai
    
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        # Инициализация клиента
        client = genai.Client(api_key=api_key)
        HAS_GENAI = True
        logger.info("✅ Google GenAI SDK (New) успешно подключен.")
    else:
        logger.warning("⚠️ GEMINI_API_KEY не найден.")
        HAS_GENAI = False

except ImportError:
    logger.error("❌ Библиотека 'google-genai' не установлена. Проверьте requirements.txt")
    HAS_GENAI = False
except Exception as e:
    logger.error(f"❌ Ошибка инициализации клиента GenAI: {e}")
    HAS_GENAI = False