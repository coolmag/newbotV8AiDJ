import logging
import json
from typing import Tuple, Optional

import google.genai as genai

from config import Settings

logger = logging.getLogger(__name__)

def analyze_message(message: str, settings: Settings) -> Tuple[str, Optional[str]]:
    """
    Анализирует сообщение пользователя с помощью Gemini (синхронно).
    Возвращает (intent, query)
    """
    if not settings.GEMINI_API_KEY:
        logger.warning("GenAI не настроен (нет ключа). Fallback на прямой поиск.")
        return "search", message

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")

        prompt = f"""Ты — умный музыкальный бот-диджей.
Проанализируй сообщение пользователя: "{message}"

Определи интент:
- "search" — если хочет конкретный трек, артиста, песню
- "radio" — если хочет включить радио, микс, волну, жанр, вайб, "давай нашу", "включи что-то", "будет движение"

Верни ТОЛЬКО чистый JSON без каких-либо комментариев и markdown:
{{"intent": "search" или "radio", "query": "уточнённый поисковый запрос для YouTube"}}

Примеры:
"давай нашу" -> {{"intent": "radio", "query": "русские хиты 2020-х"}}
"включи рок" -> {{"intent": "radio", "query": "classic rock mix"}}
"найди песню про любовь" -> {{"intent": "search", "query": "песня про любовь"}}
"будет движение?" -> {{"intent": "radio", "query": "энергичная танцевальная музыка"}}
"""

        response = model.generate_content(prompt)

        text = response.text.strip()
        if '```json' in text:
            text = text.split('```json')[1].split('```')[0].strip()
        elif '```' in text:
            text = text.replace('```', '').strip()

        result = json.loads(text)
        intent = result.get("intent", "search")
        query = result.get("query", message.strip())

        logger.info(f"Gemini анализ: '{message}' → intent={intent}, query={query}")
        return intent, query

    except Exception as e:
        logger.error(f"Ошибка анализа Gemini: {e}")
        return "search", message