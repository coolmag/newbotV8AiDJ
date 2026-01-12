import logging
import json
from typing import Tuple, Optional

try:
    from google import genai
except ImportError:
    genai = None

from config import Settings

logger = logging.getLogger(__name__)

def analyze_message(settings: Settings, message: str) -> Tuple[str, Optional[str]]:
    """
    Анализирует сообщение с помощью Gemini (синхронно).
    Использует 'from google import genai' и 'genai.configure()'.
    """
    if not genai or not settings.GEMINI_API_KEY:
        logger.warning("Gemini не доступен. Fallback.")
        return "search", message

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"Верни JSON: {{'intent': 'search' или 'radio', 'query': 'запрос'}} для: '{message}'"
        
        response = model.generate_content(prompt)
        
        text = response.text.strip()
        result = json.loads(text)

        intent = result.get("intent", "search")
        query = result.get("query", message)
        
        logger.info(f"[Gemini] '{message}' → {intent} | {query}")
        return intent, query

    except Exception as e:
        logger.error(f"Gemini ошибка: {e}")
        return "search", message
