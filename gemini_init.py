import os
import logging

# Настраиваем отдельный логгер
logger = logging.getLogger("gemini")

HAS_GENAI = False
genai = None

# Пытаемся импортировать библиотеку
try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    logger.error("❌ Библиотека 'google-generativeai' не найдена.")
    HAS_GENAI = False

# Настраиваем ключ, если библиотека есть
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

def configure_gemini():
    """Вызывается один раз при старте"""
    global HAS_GENAI
    if HAS_GENAI and GEMINI_KEY:
        try:
            genai.configure(api_key=GEMINI_KEY)
            logger.info("✅ Gemini API успешно подключен.")
        except Exception as e:
            logger.error(f"❌ Ошибка конфигурации Gemini: {e}")
            HAS_GENAI = False
    elif not GEMINI_KEY:
        logger.warning("⚠️ GEMINI_API_KEY не найден. NLP функции отключены.")

# Инициализируем сразу при импорте
configure_gemini()
