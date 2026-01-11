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

# Промпт для Диджея (Учим ИИ управлять музыкой)
PERSONAS = {
    "default": (
        "Ты DJ Aurora. Веселая, энергичная ведущая радио. "
        "Твоя главная цель — ставить музыку и развлекать. "
        "ВАЖНО: Если пользователь просит включить музыку, жанр или трек, "
        "ты ОБЯЗАНА ответить ТОЛЬКО в формате JSON: "
        '{"command": "radio", "query": "название запроса"}. '
        "Если просто болтаем — отвечай коротким текстом на русском (до 20 слов)."
    ),
    "toxic": "Ты DJ Aurora (Toxic). Саркастичная. Если просят музыку - отвечай JSON.",
}

def get_system_prompt(mode):
    return PERSONAS.get(mode, PERSONAS["default"])

class ChatManager:
    @staticmethod
    def set_mode(chat_id: int, mode: str) -> bool:
        chat_modes[chat_id] = mode
        return True

    @staticmethod
async def ask_openrouter(messages: list) -> str:
        url = "https://openrouter.ai/api/v1/chat/completions"
        api_key = os.getenv("OPENROUTER_API_KEY")
        
        if not api_key: 
            logger.error("OpenRouter Key Missing!")
            return ""
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://railway.app", 
        }
        
        # Используем твою модель KAT-Coder
        # Запасная: google/gemini-2.0-flash-lite-preview-02-05:free
        payload = {
            "model": "kwaipilot/kat-coder-pro:free", 
            "messages": messages,
            "max_tokens": 200,
            "temperature": 0.7
        }
        
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]
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

        # Обработка пустоты
        if not response_text:
            return "Связь с базой данных прервана... 🛸"

        # Если это JSON-команда - не сохраняем в историю (чтобы не зацикливать)
        if "command" in response_text and "{" in response_text:
            return response_text # Возвращаем сырой JSON для хендлера

        # Чистим текст от мусора
        if "{" not in response_text:
            # Убираем возможные теги thinking
            response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text