# nlp.py
import logging
import json
from typing import Tuple, Optional

# --- ВАЖНО: Импорт из gemini_init, чтобы разорвать круг ---
from gemini_init import genai, HAS_GENAI

logger = logging.getLogger(__name__)

def analyze_message(message: str) -> Tuple[str, Optional[str]]:
    """Анализирует сообщение через Gemini."""
    
    # Если SDK недоступен — сразу fallback
    if not HAS_GENAI or not genai:
        return "search", message

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        prompt = f"""Role: Music AI DJ.
Analyze: "{message}"
Return JSON only: {{"intent": "search"|"radio", "query": "search query"}}
"""
        response = model.generate_content([prompt])
        text = response.text.strip()
        
        # Чистим JSON от Markdown
        if "```" in text:
            text = text.replace("```json", "").replace("```", "").strip()
            
        data = json.loads(text)
        return data.get("intent", "search"), data.get("query", message[:100])

    except Exception as e:
        logger.warning(f"NLP Error: {e}")
        return "search", message