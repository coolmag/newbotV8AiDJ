import logging
import json
from typing import Optional
import httpx
import google.generativeai as genai
from config import get_settings

logger = logging.getLogger("ai_manager")
settings = get_settings() # Create a single, cached settings instance

class AIManager:
    """
    🧠 AI Manager (v2 - Corrected Settings Handling).
    Strategies:
    1. OpenRouter Free Models (Gemini, Llama, Mistral with ':free' tag).
    2. Google Gemini API (Direct fallback).
    3. Regex Fallback for ultimate reliability.
    """
    
    def __init__(self):
        self.providers = []
        
        # Настраиваем OpenRouter (если есть ключ)
        if settings.OPENROUTER_API_KEY:
            self.providers.append("OpenRouter")
            
        # Настраиваем Google Gemini (если есть ключ)
        if settings.GEMINI_API_KEY:
            try:
                genai.configure(api_key=settings.GEMINI_API_KEY)
                self.providers.append("Gemini")
            except Exception as e:
                logger.error(f"Failed to configure Gemini: {e}")

    async def analyze_message(self, text: str) -> dict:
        """
        Анализирует сообщение и возвращает JSON с интентом.
        """
        prompt = f"""
        Analyze this user message for a music bot.
        Message: "{text}"
        
        Return ONLY a JSON object (no markdown, no text) with:
        1. "intent": "radio" (if asking for genre/mood/mix) OR "search" (if specific song) OR "chat" (if random talk).
        2. "query": the clean search term or genre (translate to English if needed).
        
        Examples:
        "Play rock" -> {{'intent': 'radio', 'query': 'rock music'}}
        "Linkin Park Numb" -> {{'intent': 'search', 'query': 'Linkin Park Numb'}}
        "Привет, как дела?" -> {{'intent': 'chat', 'query': ''}}
        """

        # 1. Пробуем OpenRouter (Бесплатные модели)
        if "OpenRouter" in self.providers:
            res = await self._call_openrouter(prompt)
            if res: return res

        # 2. Пробуем Gemini (Напрямую)
        if "Gemini" in self.providers:
            res = await self._call_gemini(prompt)
            if res: return res
            
        # 3. Фолбэк (Если все AI умерли) - простая логика
        return self._regex_fallback(text)

    async def _call_openrouter(self, prompt: str) -> Optional[dict]:
        """Использует только БЕСПЛАТНЫЕ модели OpenRouter"""
        
        free_models = [
            "google/gemini-2.0-flash-exp:free",
            "google/gemini-2.0-flash-thinking-exp:free",
            "meta-llama/llama-3.2-3b-instruct:free",
            "huggingfaceh4/zephyr-7b-beta:free",
        ]
        
        headers = {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://railway.app", 
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            for model in free_models:
                try:
                    payload = {
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                    }
                    
                    resp = await client.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers=headers,
                        json=payload
                    )
                    
                    if resp.status_code == 200:
                        data = resp.json()
                        content = data['choices'][0]['message']['content']
                        logger.info(f"OpenRouter ({model}) succeeded.")
                        return self._parse_json(content)
                    else:
                        logger.warning(f"OpenRouter {model} failed: {resp.status_code}")
                        
                except Exception as e:
                    logger.error(f"OpenRouter error: {e}")
                    continue
        return None

    async def _call_gemini(self, prompt: str) -> Optional[dict]:
        try:
            model = genai.GenerativeModel('gemini-2.0-flash')
            response = await model.generate_content_async(prompt)
            logger.info("Gemini (direct) succeeded.")
            return self._parse_json(response.text)
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return None

    def _regex_fallback(self, text: str) -> dict:
        """Аварийный режим без нейросетей"""
        logger.info("⚠️ AI failed. Using Regex Fallback.")
        text_lower = text.lower()
        
        radio_keywords = ['радио', 'radio', 'play', 'играй', 'включи', 'mix', 'fm']
        if any(k in text_lower for k in radio_keywords):
            for k in radio_keywords:
                text_lower = text_lower.replace(k, '')
            query = text_lower.strip() or "top hits"
            return {"intent": "radio", "query": query}
            
        return {"intent": "search", "query": text}

    def _parse_json(self, text: str) -> Optional[dict]:
        """Очищает и парсит JSON из ответа AI."""
        try:
            cleaned = text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned.split("\n", 1)[1]
                if cleaned.endswith("```"):
                    cleaned = cleaned.rsplit("\n", 1)[0]
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:-3]

            return json.loads(cleaned)
        except Exception as e:
            logger.error(f"Failed to parse AI JSON response: {e} | Response: '{text[:100]}'")
            return None
