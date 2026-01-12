import os
import logging
import time
from google import genai
from google.genai import types

logger = logging.getLogger("gemini")
HAS_GENAI = False
client = None
MODELS = ['gemini-1.5-flash', 'gemini-2.0-flash-exp']

try:
    k = os.getenv("GEMINI_API_KEY")
    if k:
        client = genai.Client(api_key=k)
        HAS_GENAI = True
except: pass

def generate_smart(prompt: str) -> str:
    if not HAS_GENAI or not client: return None
    for m in MODELS:
        try:
            # Явный конфиг с таймаутом (если поддерживается, или просто надеемся на быстрый ответ)
            response = client.models.generate_content(
                model=m, 
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.7)
            )
            return response.text
        except Exception as e:
            logger.error(f"Gemini {m} error: {e}")
            time.sleep(1)
    return None
