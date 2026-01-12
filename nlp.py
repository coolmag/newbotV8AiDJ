import logging
import json
from typing import Tuple, Optional

try:
    import genai
except ImportError:
    genai = None

from config import Settings

logger = logging.getLogger(__name__)

async def analyze_message(message: str, settings: Settings) -> Tuple[str, Optional[str]]:
    """
    Анализирует сообщение пользователя с помощью Gemini, используя правильный SDK (genai).
    """
    if not genai or not settings.GEMINI_API_KEY:
        logger.warning("GenAI не доступен (нет ключа или SDK). Fallback на прямой поиск.")
        return "search", message

    try:
        model = genai.GenerativeModel(model_name="gemini-1.5-flash")

        prompt = f"""Ты музыкальный AI-диджей.
Сообщение: "{message}"

Определи интент:
- "search" — конкретный трек/артист
- "radio" — микс, жанр, вайб, "давай", "включи что-то", "будет движение"

Верни ТОЛЬКО JSON:
{{"intent": "search" или "radio", "query": "готовый запрос для YouTube"}}

Примеры:
"давай давай" -> {{"intent": "radio", "query": "энергичные русские хиты"}}
"хорошо" -> {{"intent": "radio", "query": "chill расслабляющая музыка"}}
"""
        # ИСПОЛЬЗУЕМ ASYNC ВЕРСИЮ, ТАК КАК ФУНКЦИЯ АСИНХРОННАЯ
        response = await model.generate_content_async(prompt)

        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:].split("```")[0].strip()

        result = json.loads(text)
        intent = result.get("intent", "search")
        query = result.get("query", message)

        logger.info(f"[Gemini] {message} → {intent} | {query}")
        return intent, query

    except Exception as e:
        logger.error(f"Gemini ошибка: {e}")
        return "search", message
