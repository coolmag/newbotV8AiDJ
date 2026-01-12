import logging
import json
from typing import Tuple, Optional

# Импорт должен быть google.generativeai
try:
    import google.generativeai as genai
except ImportError:
    genai = None

# Импортируем глобальные флаги из main.py
from gemini_init import HAS_GENAI 

logger = logging.getLogger(__name__)

def analyze_message(message: str) -> Tuple[str, Optional[str]]:
    # 1. Эвристика (Fallback)
    def heuristic():
        msg = message.lower()
        if any(x in msg for x in ['play', 'включи', 'найди', 'играй']): return "search", message
        if len(message) > 40: return "search", message
        return "chat", ""

    if not HAS_GENAI or not genai: return heuristic()

    try:
        # ИСПРАВЛЕНИЕ: Используем 'gemini-pro' (единственная стабильная модель для этой версии либы)
        model = genai.GenerativeModel("gemini-pro")
        
        prompt = f"""Analyze: "{message}"
JSON: {{"intent": "search"|"radio"|"chat", "query": "text"}}"""
        
        response = model.generate_content([prompt])
        text = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        return data.get("intent", "chat"), data.get("query", message)
    except Exception as e:
        logger.warning(f"NLP Error: {e}")
        return heuristic()