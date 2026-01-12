import logging
import random
import re
import json
from collections import deque, defaultdict
import httpx
import asyncio

from ai_config import get_active_providers, AIProviderConfig
# Импортируем нашу новую функцию
from gemini_init import generate_smart, HAS_GENAI

logger = logging.getLogger(__name__)

chat_histories = defaultdict(lambda: deque(maxlen=6))
chat_modes = defaultdict(lambda: "default")

PERSONAS = {
    "default": "Ты DJ Aurora. Веселая, дерзкая. Отвечай кратко.",
    "toxic": "Ты DJ Aurora (Toxic). Хами.",
    "gop": "Ты Аврора с района. Дерзкая.",
    "chill": "Ты Аврора (Chill). Спокойная.",
    "quiz": "Ты Ведущая Викторины."
}

BACKUP_PHRASES = ["Связь с космосом барахлит... 🎧", "Сигнал потерян... 🎶"]

def get_system_prompt(mode):
    return PERSONAS.get(mode, PERSONAS["default"]) + " (Language: Russian, Max length: 20 words)"

class ChatManager:
    @staticmethod
    def set_mode(chat_id: int, mode: str):
        chat_modes[chat_id] = mode
    @staticmethod
    def get_mode(chat_id: int): return chat_modes[chat_id]

    @staticmethod
    async def _call_provider(client: httpx.AsyncClient, provider: AIProviderConfig, messages: list) -> str:
        try:
            headers = {"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"}
            payload = {"model": provider.model, "messages": messages, "max_tokens": 150}
            resp = await client.post(provider.base_url, json=payload, headers=headers, timeout=5.0)
            if resp.status_code == 200: return resp.json()["choices"][0]["message"]["content"]
        except: pass
        return None

    @staticmethod
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        messages = [{"role": "system", "content": get_system_prompt(mode)}]
        for msg in history: messages.append(msg)
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        # 1. External Providers (Groq, OpenRouter)
        async with httpx.AsyncClient() as http_client:
            for provider in get_active_providers():
                if res := await ChatManager._call_provider(http_client, provider, messages):
                    history.append({"role": "user", "content": user_text})
                    history.append({"role": "assistant", "content": res})
                    return res
        
        # 2. Native Gemini (Smart Wrapper)
        # Собираем историю в один текст для Gemini
        full_prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
        
        # Запускаем в отдельном потоке, так как generate_smart синхронная
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, lambda: generate_smart(full_prompt))
        
        if res:
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": res})
            return res

        return random.choice(BACKUP_PHRASES)
