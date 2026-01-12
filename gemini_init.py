import os
import logging
import time
import random

logger = logging.getLogger("gemini")

HAS_GENAI = False
client = None

# Добавили модели попроще в конец списка
MODELS = [
    'gemini-2.0-flash-exp',
    'gemini-1.5-flash',
    'gemini-1.5-flash-8b'
]

try:
    from google import genai
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        client = genai.Client(api_key=api_key)
        HAS_GENAI = True
        logger.info("✅ Google GenAI SDK подключен.")
    else:
        logger.warning("⚠️ GEMINI_API_KEY не найден.")

except ImportError:
    logger.error("❌ Библиотека 'google-genai' не установлена.")

def generate_smart(prompt: str) -> str:
    if not HAS_GENAI or not client: return None

    for model_name in MODELS:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            return response.text
            
        except Exception as e:
            e_str = str(e)
            if "429" in e_str or "RESOURCE_EXHAUSTED" in e_str:
                logger.warning(f"⏳ Limit on {model_name}. Waiting 2s...")
                time.sleep(2) # Небольшая пауза, вдруг отпустит
                continue 
            
            if "404" in e_str: continue # Модель не найдена - идем дальше
            
            logger.error(f"❌ Error {model_name}: {e}")
            continue

    return None
