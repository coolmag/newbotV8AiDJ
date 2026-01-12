import logging
import json
from typing import Tuple, Optional

try:
    from google import genai
except ImportError:
    genai = None

from config import Settings
# Импортируем глобальный клиент, созданный в main.py
from main import genai_client, HAS_GENAI

logger = logging.getLogger(__name__)

def analyze_message(message: str, settings: Settings) -> Tuple[str, Optional[str]]:
    """
    Анализирует сообщение (синхронно), используя последнюю версию API (январь 2026).
    """
    # Проверка на уровне вызова, а не импорта
    if not HAS_GENAI or genai_client is None:
        logger.warning("Gemini клиент недоступен → fallback на search.")
        return "search", message

    try:
        # Используем глобальный клиент, чтобы не создавать его каждый раз
        model = genai_client.get_model("gemini-1.5-flash")

        prompt = f"""Анализируй запрос для музыкального бота: "{message}"

Интент: "search" (конкретный трек/артист) или "radio" (микс, жанр, вайб, "давай", "включи").

Верни ТОЛЬКО чистый JSON без markdown и лишних слов:
{{"intent": "search" или "radio", "query": "короткий поисковый запрос для YouTube"}}

Примеры:
"давай давай" → {{"intent": "radio", "query": "энергичные хиты"}}
"кайф" → {{"intent": "radio", "query": "кайфовая музыка"}}
"что нового?" → {{"intent": "search", "query": "новинки музыки"}}
"""
        # Правильный вызов в 2026 SDK — contents как список строк
        response = model.generate_content(
            contents=[prompt],
            generation_config={"temperature": 0.7, "max_output_tokens": 150}
        )

        text = response.text.strip()
        if text.startswith("```json"):
            text = text.split("```json", 1)[1].rsplit("```", 1)[0].strip()

        result = json.loads(text)
        intent = result.get("intent", "search")
        query = result.get("query", message[:100])

        logger.info(f"[Gemini] '{message}' → intent={intent}, query='{query}'")
        return intent, query

    except Exception as e:
        logger.error(f"Gemini ошибка: {str(e)[:300]}")
        return "search", message[:100]
