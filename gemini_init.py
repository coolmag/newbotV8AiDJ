import os
import logging
import asyncio
import time
import random

# Настраиваем логгер
logger = logging.getLogger("gemini")

HAS_GENAI = False
client = None

# Список моделей в порядке приоритета
# 1. 2.0 Flash Exp (Самая умная и быстрая)
# 2. 1.5 Flash (Самая стабильная для продакшена)
# 3. 1.5 Flash 8B (Самая дешевая/легкая)
# 4. 1.5 Pro (Тяжелая артиллерия, если все упало)
MODELS = [
    'gemini-2.0-flash-exp',
    'gemini-1.5-flash',
    'gemini-1.5-flash-8b',
    'gemini-1.5-pro'
]

try:
    from google import genai
    from google.genai import types
    
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        client = genai.Client(api_key=api_key)
        HAS_GENAI = True
        logger.info("✅ Google GenAI SDK (Smart Wrapper) подключен.")
    else:
        logger.warning("⚠️ GEMINI_API_KEY не найден.")

except ImportError:
    logger.error("❌ Библиотека 'google-genai' не установлена.")

def generate_smart(prompt: str) -> str:
    """
    Умная генерация: перебирает модели и делает повторные попытки при 429.
    Возвращает текст ответа или None, если все провалилось.
    """
    if not HAS_GENAI or not client:
        return None

    for model_name in MODELS:
        try:
            # logger.info(f"Trying model: {model_name}")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            return response.text
            
        except Exception as e:
            e_str = str(e)
            
            # Если ошибка 429 (Too Many Requests) - пробуем подождать чуть-чуть
            if "429" in e_str or "RESOURCE_EXHAUSTED" in e_str:
                logger.warning(f"⚠️ Limit hit on {model_name}. Trying next...")
                time.sleep(1) # Короткая пауза перед следующей моделью
                continue # Идем к следующей модели в списке
            
            # Если модель не найдена (404) - сразу к следующей
            if "404" in e_str or "NOT_FOUND" in e_str:
                # logger.warning(f"⚠️ Model {model_name} not found. Skipping.")
                continue
                
            logger.error(f"❌ Error on {model_name}: {e}")
            continue

    logger.error("💀 All models failed.")
    return None
