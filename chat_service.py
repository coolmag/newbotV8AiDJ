import logging
import random
import re
import json
import os
from collections import deque, defaultdict
import asyncio
import httpx 

logger = logging.getLogger(__name__)

chat_histories = defaultdict(lambda: deque(maxlen=6))
chat_modes = defaultdict(lambda: "default")

PERSONAS = {
    "default": "Ты DJ Aurora. Веселая, дерзкая. Если просят музыку — отвечай JSON-ом: {\"command\": \"radio\", \"query\": \"жанр\"}. Иначе — просто текстом.",
    "toxic": "Ты DJ Aurora (Токсик). Если просят музыку — отвечай JSON. Иначе — дерзи."
}

def get_system_prompt(mode):
    return PERSONAS.get(mode, PERSONAS["default"]) + " (Отвечай на русском)."

class ChatManager:
    @staticmethod
    def set_mode(chat_id: int, mode: str) -> bool:
        chat_modes[chat_id] = mode
        return True

    @staticmethod
    def clean_response(text: str) -> str:
        if not text: return ""
        # Если это JSON-команда, возвращаем как есть
        if "{" in text and "}" in text and "command" in text:
            return text
        
        text = re.sub(r'http[s]?://\S+', '', text)
        junk = ["Novita", "AI model", "OpenAI"]
        for phrase in junk: text = re.sub(f"(?i){phrase}", "Aurora", text)
        return text.strip()

    @staticmethod
    async def ask_novita(messages: list) -> str:
        # Используем llama-3 (она часто доступна бесплатно)
        url = "https://api.novita.ai/v3/openai/chat/completions"
        api_key = os.getenv("NOVITA_API_KEY", "")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "meta-llama/llama-3.1-8b-instruct",
            "messages": messages,
            "max_tokens": 100
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]
                logger.error(f"Novita Status: {resp.status_code} {resp.text}")
        except Exception as e:
            logger.error(f"Novita Error: {e}")
        return ""

    @staticmethod
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        system_prompt = get_system_prompt(mode)
        
        messages = [{"role": "system", "content": system_prompt}]
        for msg in history: messages.append(msg)
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        # Запрос
        response_text = await ChatManager.ask_novita(messages)

        # Fallback (DuckDuckGo как резерв, если Novita отказала)
        if not response_text:
             # ... тут можно добавить вызов DDG из прошлого кода ...
             pass

        if not response_text:
            return "Связь прервана... 🔇"

        # Не сохраняем JSON-команды в историю, чтобы не путать ИИ
        if "command" not in response_text:
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": response_text})
        
        return response_text