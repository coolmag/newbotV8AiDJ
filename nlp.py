import logging
import json
from typing import Tuple, Optional

try:
    from google import genai
except ImportError:
    genai = None

from config import Settings

logger = logging.getLogger(__name__)

def analyze_message(message: str, settings: Settings) -> Tuple[str, Optional[str]]:
    """
    Анализирует сообщение с помощью Gemini (синхронно), 
    опираясь на авто-конфигурацию по GEMINI_API_KEY.
    """
    if genai is None:
        logger.warning("GenAI SDK не установлен. Fallback.")
        return "search", message

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")

        prompt = f"""Анализируй сообщение для бота-диджея: "{message}"

Интент: "search" (конкретный трек) или "radio" (микс, жанр, вайб).

Верни ТОЛЬКО JSON:
{{"intent": "search"|"radio", "query": "запрос для YouTube"}}

Примеры:
"давай давай" -> {{"intent": "radio", "query": "энергичные русские хиты"}}
"""

        response = model.generate_content(prompt)

        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:].rsplit("```", 1)[0].strip()

        result = json.loads(text)
        intent = result.get("intent", "search")
        query = result.get("query", message)

        logger.info(f"[Gemini] {message} → {intent} | {query}")
        return intent, query

    except Exception as e:
        logger.error(f"Gemini ошибка: {e}")
        return "search", message