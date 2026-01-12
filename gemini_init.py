# gemini_init.py
import os
import logging

logger = logging.getLogger("gemini")

HAS_GENAI = False
genai = None

try:
    # Пытаемся импортировать стандартную библиотеку
    import google.generativeai as genai
    
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
        HAS_GENAI = True
        logger.info("✅ Gemini (Google AI) успешно подключен.")
    else:
        logger.warning("⚠️ GEMINI_API_KEY не найден.")
        HAS_GENAI = False

except ImportError:
    logger.error("❌ Библиотека google-generativeai не установлена.")
    HAS_GENAI = False
except Exception as e:
    logger.error(f"❌ Ошибка инициализации Gemini: {e}")
    HAS_GENAI = False