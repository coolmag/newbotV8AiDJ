import logging
from typing import Optional, Tuple
import json

import google.genai as genai

from config import Settings

logger = logging.getLogger(__name__)

async def analyze_message(message: str, settings: Settings) -> Tuple[str, Optional[str]]:
    """
    Анализирует текстовое сообщение с помощью Gemini для определения интента.
    
    Возвращает: (intent, query) где intent - 'search' или 'radio', query - уточненный запрос.
    Fallback на простой поиск если AI недоступен.
    """
    if not settings.GEMINI_API_KEY:
        logger.warning("Gemini API key missing. Falling back to direct search.")
        return "search", message  # Fallback: Трактовать как поиск трека
    
    try:
        # Модель и конфигурация genai уже должны быть установлены в main.py
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        prompt = (
            f"Анализируй запрос пользователя для музыкального бота: '{message}'.\n"
            "Определи интент: 'search' (поиск конкретного трека/артиста) или 'radio' (случайный микс по жанру/настроению).\n"
            "Верни ТОЛЬКО валидный JSON с двумя ключами: {\"intent\": \"search|radio\", \"query\": \"уточненный поисковый запрос\"}.\n"
            "Примеры:\n"
            "- для 'включи раммштайн' -> {\"intent\": \"search\", \"query\": \"Rammstein\"}\n"
            "- для 'хочу послушать рок' -> {\"intent\": \"radio\", \"query\": \"rock music mix\"}\n"
            "- для 'удиви меня' -> {\"intent\": \"radio\", \"query\": \"random popular music\"}"
        )
        response = await model.generate_content_async(prompt)
        
        # Улучшенный парсинг JSON из ответа модели
        json_text = response.text.strip()
        if json_text.startswith("```json"):
            json_text = json_text[7:]
        if json_text.endswith("```"):
            json_text = json_text[:-3]
        
        result = json.loads(json_text.strip())
        
        intent = result.get('intent')
        query = result.get('query')

        # Валидация ответа от AI
        if intent not in ['search', 'radio'] or not query:
             raise ValueError(f"Invalid intent or query from AI: {result}")

        logger.info(f"NLP result: intent='{intent}', query='{query}'")
        return intent, query

    except Exception as e:
        logger.error(f"NLP analysis failed for message '{message}'. Error: {e}. Falling back to direct search.")
        return "search", message  # Graceful degradation
