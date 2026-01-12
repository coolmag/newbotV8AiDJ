import os
import logging
import time
from google import genai

logger = logging.getLogger("gemini")
HAS_GENAI = False
client = None
MODELS = ['gemini-1.5-flash', 'gemini-1.5-flash-8b', 'gemini-2.0-flash-exp']

try:
    if k := os.getenv("GEMINI_API_KEY"):
        client = genai.Client(api_key=k)
        HAS_GENAI = True
except: pass

def generate_smart(prompt: str) -> str:
    if not HAS_GENAI or not client: return None
    for m in MODELS:
        try:
            return client.models.generate_content(model=m, contents=prompt).text
        except Exception: time.sleep(1)
    return None