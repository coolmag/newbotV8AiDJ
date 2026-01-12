import logging
import json
from typing import Tuple, Optional

try:
    from google.genai import types
except ImportError:
    types = None

from config import Settings
# Импортируем глобальный клиент, созданный в main.py
from main import genai_client, HAS_GENAI

logger = logging.getLogger(__name__)

def analyze_message(message: str, settings: Settings) -> Tuple[str, Optional[str]]:
    """
    Анализирует сообщение (синхронно), используя глобальный genai_client.
    Использует client.models.generate_content API.
    """
    if not HAS_GENAI or genai_client is None:
        logger.warning("Gemini клиент недоступен → fallback на search.")
        return "search", message

    try:
        prompt = f"""Анализируй запрос для музыкального бота: "{message}"

Интент: "search" (конкретный трек) или "radio" (микс/жанр/вайб).

Верни ТОЛЬКО чистый JSON:
{{"intent": "search" или "radio", "query": "короткий запрос для YouTube"}}

Примеры:
"давай давай" → {{"intent": "radio", "query": "энергичные хиты"}}
"""

        # Используем API через созданный клиент
        response = genai_client.models.generate_content(
            model="gemini-1.5-flash",
            contents=[types.Part.from_text(prompt)],
            generation_config=types.GenerationConfig(
                temperature=0.7, 
                max_output_tokens=200
            )
        )

        text = response.text.strip()
        if text.startswith("```json"):
            text = text.split("```json", 1)[1].rsplit("```", 1)[0].strip()

        result = json.loads(text)
        intent = result.get("intent", "search")
        query = str(result.get("query", message[:100]))

        logger.info(f"[Gemini] {message} → {intent} | {query}")
        return intent, query

    except Exception as e:
        logger.error(f"Gemini ошибка: {str(e)[:200]}")
        return "search", message[:100]