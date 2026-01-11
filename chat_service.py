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
    async def ask_openrouter(messages: list) -> str:
        url = "https://openrouter.ai/api/v1/chat/completions"
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key: return ""
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://aurora.radio", 
        }
        
        # ЭКЗОТИЧЕСКИЕ БЕСПЛАТНЫЕ МОДЕЛИ (Обычно свободны)
        models_to_try = [
            "kwaipilot/kat-coder-pro:free", # Твой выбор
            "cognitivecomputations/dolphin3.0-r1-mistral-24b:free",
            "mattshumer/reflection-70b:free",
            "mistralai/mistral-7b-instruct:free",
            "google/gemini-2.0-flash-lite-preview-02-05:free"
        ]
        
        async with httpx.AsyncClient(timeout=20.0) as client:
            for model in models_to_try:
                try:
                    payload = {
                        "model": model, 
                        "messages": messages,
                        "max_tokens": 250,
                        "temperature": 0.8
                    }
                    
                    resp = await client.post(url, json=payload, headers=headers)
                    
                    if resp.status_code == 200:
                        content = resp.json()["choices"][0]["message"]["content"]
                        if content and len(content) > 1: return content
                    
                    # Если ошибка 429 - пробуем следующую модель
                    logger.warning(f"Model {model} busy: {resp.status_code}")
                    await asyncio.sleep(0.2)
                except: continue
                
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

        if not response_text:
            response_text = random.choice(BACKUP_PHRASES)

        if "command" in response_text and "{" in response_text:
            return response_text 

        response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()
        
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text
