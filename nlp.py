import logging
from typing import Optional, Tuple, Any
import json

import google.genai as genai

from config import Settings

logger = logging.getLogger(__name__)

async def analyze_message(message: str, genai_client: Optional[Any]) -> Tuple[str, Optional[str]]:
    """
    Анализирует текстовое сообщение с помощью Gemini для определения интента,
    используя новый SDK (январь 2026).
    
    Возвращает: (intent, query) где intent - 'search' или 'radio', query - уточненный запрос.
    """
    if not genai_client:
        logger.warning("GenAI client not available. Falling back to direct search.")
        return "search", message

    try:
        # Новый способ получения модели (2026)
        model = genai_client.get_model("gemini-3-flash-preview")

        prompt = (
            f"Анализируй этот запрос для музыкального бота: '{message}'.\n"
            "Твоя задача - определить намерение ('intent') и извлечь поисковый запрос ('query').\n"
            "Варианты 'intent': 'search' (поиск трека/артиста) или 'radio' (микс по жанру/настроению).\n"
            "Верни ТОЛЬКО чистый JSON без markdown и лишних слов.\n"
            "Примеры:\n"
            "1. Запрос: 'включи рамштайн' -> {\"intent\": \"search\", \"query\": \"Rammstein\"}\n"
            "2. Запрос: 'хочу послушать что-то спокойное' -> {\"intent\": \"radio\", \"query\": \"lo-fi hip hop mix\"}\n"
            "3. Запрос: 'давай нашу' -> {\"intent\": \"radio\", \"query\": \"русские хиты 2020-х\"}"
        )

        # Новый асинхронный метод генерации
        response = await model.generate_content_async(prompt)
        
        text = response.text.strip()
        result = json.loads(text)
        
        intent = result.get("intent", "search")
        query = result.get("query", message)

        if intent not in ['search', 'radio'] or not isinstance(query, str):
            raise ValueError(f"AI returned invalid data: intent='{intent}', query='{query}'")

        logger.info(f"NLP result: intent='{intent}', query='{query}'")
        return intent, query

    except Exception as e:
        logger.error(f"NLP analysis failed for '{message}'. Error: {e}. Falling back to direct search.")
        return "search", message