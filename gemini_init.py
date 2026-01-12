# gemini_init.py
import os
import logging

logger = logging.getLogger("gemini")

HAS_GENAI = False
genai = None

# Пытаемся импортировать библиотеку
try:
    import google.generativeai as genai
    
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
        HAS_GENAI = True
        logger.info("✅ Gemini API успешно подключен.")
        
        # --- DEBUG: Вывод доступных моделей в лог ---
        try:
            logger.info("🔍 Доступные модели:")
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    logger.info(f"   - {m.name}")
        except Exception as e:
            logger.warning(f"Не удалось получить список моделей: {e}")
        # --------------------------------------------
            
    else:
        logger.warning("⚠️ Нет ключа API.")
        HAS_GENAI = False

except ImportError:
    logger.error("❌ Библиотека 'google-generativeai' не найдена.")
    HAS_GENAI = False
except Exception as e:
    logger.error(f"❌ Ошибка инициализации Gemini: {e}")
    HAS_GENAI = False

