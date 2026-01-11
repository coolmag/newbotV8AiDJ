import logging
import os
import random
import re
import json
from collections import deque, defaultdict
import asyncio
import httpx 

logger = logging.getLogger(__name__)

chat_histories = defaultdict(lambda: deque(maxlen=6))
chat_modes = defaultdict(lambda: "default")

PERSONAS = {
    "default": "Ты DJ Aurora. Веселая и дерзкая. Если просят музыку - отвечай JSON: {\"command\": \"radio\", \"query\": \"жанр\"}. Иначе - текст (до 20 слов).",
    "toxic": "Ты DJ Aurora (Toxic). Дерзкая.",
}

def get_system_prompt(mode):
    return PERSONAS.get(mode, PERSONAS["default"]) + " (Language: Russian)"

BACKUP_PHRASES = [
    "Связь с космосом барахлит, но музыка играет! 🎧",
    "Аврора на связи! (ИИ перезагружается)",
    "Что-то интернет лагает, повтори?"
]

class ChatManager:
    @staticmethod
    def set_mode(chat_id: int, mode: str) -> bool:
        chat_modes[chat_id] = mode
        return True
    
    @staticmethod
    def get_mode(chat_id: int) -> str:
        return chat_modes[chat_id]

    @staticmethod
    async def ask_openrouter(messages: list) -> str:
        url = "https://openrouter.ai/api/v1/chat/completions"
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key: return ""
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://aurora.radio", 
        }
        
        # GEMINI FLASH LITE (Самая быстрая и бесплатная)
        payload = {
            "model": "google/gemini-2.0-flash-lite-preview-02-05:free", 
            "messages": messages,
            "max_tokens": 200,
            "temperature": 0.8
        }
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"]
                    logger.info(f"[AI] Response: {content[:50]}...") # Логируем ответ
                    return content
                else:
                    logger.error(f"OpenRouter Error: {resp.status_code} {resp.text}")
        except Exception as e:
            logger.error(f"OpenRouter Connection Error: {e}")
        return ""

    @staticmethod
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        system_prompt = get_system_prompt(mode)
        
        messages = [{"role": "system", "content": system_prompt}]
        for msg in history: messages.append(msg)
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        # ЗАПРОС
        response_text = await ChatManager.ask_openrouter(messages)

        if not response_text:
            response_text = random.choice(BACKUP_PHRASES)

        # JSON команды
        if "command" in response_text and "{" in response_text:
            return response_text 

        response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()
        
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text