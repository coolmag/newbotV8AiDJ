import logging
import json
from typing import Tuple, Optional

# Импортируем новый клиент
from gemini_init import client, HAS_GENAI

logger = logging.getLogger(__name__)

def analyze_message(message: str) -> Tuple[str, Optional[str]]:
    # Эвристика на случай отключения
    def heuristic():
        msg = message.lower()
        if any(x in msg for x x in ['play', 'включи', 'найди', 'играй']): return "search", message
        if len(message) > 40: return "search", message
        return "chat", ""

    if not HAS_GENAI or not client:
        return heuristic()

    try:
        prompt = f"""Analyze this user message: "{message}"

Classify into 3 INTENTS:
1. "search" -> Request for specific song/artist.
2. "radio" -> Request for genre/vibe.
3. "chat" -> Conversational/greetings.

Return JSON ONLY:
{{"intent": "search"|"radio"|"chat", "query": "search query or empty"}}
"""
        # НОВЫЙ СИНТАКСИС ВЫЗОВА
        # Используем самую быструю модель
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt
        )
        
        text = response.text.strip()
        if "```" in text:
            text = text.replace("```json", "").replace("```", "").strip()
            
        data = json.loads(text)
        return data.get("intent", "chat"), data.get("query", message)

    except Exception as e:
        logger.warning(f"[NLP] API Error: {e}")
        return heuristic()
