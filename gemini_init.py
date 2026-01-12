import os
import logging

# Настраиваем логгер
logger = logging.getLogger("gemini")

HAS_GENAI = False
client = None

try:
    # Используем новый SDK
    from google import genai
    
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        # Инициализация синхронного клиента
        client = genai.Client(api_key=api_key)
        HAS_GENAI = True
        logger.info("✅ Google GenAI (v2.0) подключен.")
    else:
        logger.warning("⚠️ GEMINI_API_KEY не найден.")
        HAS_GENAI = False

except ImportError:
    logger.error("❌ Библиотека 'google-genai' не установлена. Проверьте requirements.txt")
    HAS_GENAI = False
except Exception as e:
    logger.error(f"❌ Ошибка init GenAI: {e}")
    HAS_GENAI = False
