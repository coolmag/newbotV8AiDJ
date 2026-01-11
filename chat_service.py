import logging
import os
import random
import re
import json
from collections import deque, defaultdict
import asyncio
import httpx 

logger = logging.getLogger(__name__)

chat_histories = defaultdict(lambda: deque(maxlen=10))
chat_modes = defaultdict(lambda: "default") # Глобальная переменная

PERSONAS = {
    "default": (
        "Ты — DJ Aurora. "
        "Если просят музыку - отвечай JSON: {\"command\": \"radio\", \"query\": \"жанр\"}. "
        "Иначе - текст (до 20 слов)."
    ),
    "toxic": "Ты DJ Aurora (Toxic).",
    "quiz": "Ты ведущая викторины."
}

def get_system_prompt(mode):
    return PERSONAS.get(mode, PERSONAS["default"]) + " (Language: Russian)"

class ChatManager:
    @staticmethod
    def get_mode(chat_id: int) -> str:
        return chat_modes[chat_id]

    @staticmethod
    def set_mode(chat_id: int, mode: str) -> bool:
        if mode in PERSONAS:
            chat_modes[chat_id] = mode
            chat_histories[chat_id].clear()
            return True
        return False

    @staticmethod
    async def ask_openrouter(messages: list) -> str:
        url = "https://openrouter.ai/api/v1/chat/completions"
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key: return ""
        
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "HTTP-Referer": "https://aurora.radio"}
        payload = {"model": "google/gemini-2.0-flash-exp:free", "messages": messages, "max_tokens": 200, "temperature": 0.8}
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200: return resp.json()["choices"][0]["message"]["content"]
        except: pass
        return ""

    @staticmethod
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        system_prompt = get_system_prompt(mode)
        
        messages = [{"role": "system", "content": system_prompt}]
        for msg in history: messages.append(msg)
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        response_text = await ChatManager.ask_openrouter(messages)

        if not response_text: return "Связь потеряна... 📡"
        if "command" in response_text and "{" in response_text: return response_text 

        response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        return response_text