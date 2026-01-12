import logging
import random
import re
import json
from collections import deque, defaultdict
import httpx
import asyncio

from ai_config import get_active_providers, AIProviderConfig
from gemini_init import generate_smart, HAS_GENAI

logger = logging.getLogger(__name__)

chat_histories = defaultdict(lambda: deque(maxlen=6))
chat_modes = defaultdict(lambda: "default")

PERSONAS = {
    "default": "Ты DJ Aurora. Веселая, дерзкая. Отвечай кратко.",
    "toxic": "Ты DJ Aurora (Toxic). Саркастичная, язвительная. Хами.",
    "gop": "Ты Аврора с района. Дерзкая.",
    "chill": "Ты Аврора (Chill). Спокойная.",
    "quiz": "Ты Ведущая Викторины."
}

BACKUP_PHRASES = [
    "Связь с космосом барахлит... 🎧",
    "Все нейросети заняты, подожди... 🎶",
    "Эфир перегружен! 🔥"
]

def get_system_prompt(mode):
    return PERSONAS.get(mode, PERSONAS["default"]) + " (Language: Russian, Max length: 30 words)"

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
            
            # Разные провайдеры требуют разный формат, но OpenAI-compatible (Novita, Groq, OpenRouter) одинаковы
            payload = {
                "model": provider.model, 
                "messages": messages, 
                "max_tokens": 150,
                "temperature": 0.7
            }
            
            # HuggingFace требует чуть другую структуру URL иногда, но v1/chat/completions стандартна
            
            resp = await client.post(provider.base_url, json=payload, headers=headers, timeout=6.0)
            
            if resp.status_code == 200:
                data = resp.json()
                if "choices" in data and len(data["choices"]) > 0:
                    return data["choices"][0]["message"]["content"]
            
            logger.warning(f"[AI] {provider.name} error {resp.status_code}: {resp.text[:100]}")
            
        except Exception as e:
            logger.warning(f"[AI] {provider.name} exception: {e}")
        return None

    @staticmethod
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        messages = [{"role": "system", "content": get_system_prompt(mode)}]
        for msg in history: messages.append(msg)
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        # 1. ПЕРЕБОР ВНЕШНИХ ПРОВАЙДЕРОВ (Novita -> Groq -> OpenRouter -> HF)
        async with httpx.AsyncClient() as http_client:
            for provider in get_active_providers():
                # logger.info(f"Trying {provider.name}...")
                if res := await ChatManager._call_provider(http_client, provider, messages):
                    history.append({"role": "user", "content": user_text})
                    history.append({"role": "assistant", "content": res})
                    return res
        
        # 2. Native Gemini (Последний шанс)
        logger.info("⚠️ All external providers failed. Using Gemini Backup.")
        full_prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, lambda: generate_smart(full_prompt))
        
        if res:
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": res})
            return res

        return random.choice(BACKUP_PHRASES)
