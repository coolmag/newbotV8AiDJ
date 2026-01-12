import logging
import json
from typing import Tuple, Optional

# Импортируем нашу новую функцию
from gemini_init import generate_smart, HAS_GENAI

logger = logging.getLogger(__name__)

def analyze_message(message: str) -> Tuple[str, Optional[str]]:
    # Эвристика (Fallback)
    def heuristic():
        msg = message.lower()
        if any(x in msg for x in ['play', 'включи', 'найди', 'играй']): return "search", message
        if len(message) > 40: return "search", message
        return "chat", ""

    if not HAS_GENAI: return heuristic()

    try:
        prompt = f"""Analyze message: "{message}"

INTENTS:
1. search (song/artist request)
2. radio (genre/mood request)
3. chat (conversation)

Return JSON ONLY: {{"intent": "search"|"radio"|"chat", "query": "text"}}"""

        # ВЫЗЫВАЕМ УМНУЮ ФУНКЦИЮ
        text = generate_smart(prompt)
        
        if not text:
            return heuristic()
            
        text = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        return data.get("intent", "chat"), data.get("query", message)

    except Exception as e:
        logger.warning(f"[NLP] Error: {e}")
        return heuristic()