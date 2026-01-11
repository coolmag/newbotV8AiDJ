import logging
import random
import re
import json
import urllib.parse
from collections import deque, defaultdict
import asyncio
import httpx # Для запросов

logger = logging.getLogger(__name__)

chat_histories = defaultdict(lambda: deque(maxlen=6))
chat_modes = defaultdict(lambda: "default")

PERSONAS = {
    "default": "Ты DJ Aurora. Веселая, дерзкая радиоведущая. Твои ответы короткие и с юмором. Ты обожаешь музыку. Используй эмодзи.",
    "toxic": "Ты DJ Aurora. Ты саркастичная и язвительная. Ты считаешь вкусы людей ужасными.",
    "gop": "Ты Аврора. Говоришь на уличном сленге, дерзко, 'тыкаешь'.",
    "chill": "Ты Аврора. Спокойная, мягкая, загадочная.",
    "quiz": "Ты ведущая викторины."
}

def get_system_prompt(mode):
    return PERSONAS.get(mode, PERSONAS["default"]) + " (Отвечай на русском языке, максимум 2 предложения)."

class ChatManager:
    @staticmethod
    def set_mode(chat_id: int, mode: str) -> bool:
        if mode in PERSONAS:
            chat_modes[chat_id] = mode
            chat_histories[chat_id].clear()
            return True
        return False

    @staticmethod
    def clean_response(text: str) -> str:
        if not text: return ""
        text = re.sub(r'http[s]?://\S+', '', text)
        junk = ["Pollinations", "OpenAI", "ChatGPT", "AI model", "language model"]
        for phrase in junk:
            text = re.sub(f"(?i){phrase}", "Aurora", text)
        return text.strip()

    # --- POLLINATIONS GEN API (2026 STABLE) ---
    @staticmethod
    async def ask_pollinations(messages: list) -> str:
        # Мы используем метод GET, так как он самый надежный для этого API
        # Собираем промпт
        full_prompt = ""
        for msg in messages:
            full_prompt += f"{msg['role']}: {msg['content']}\n"
        
        # Кодируем для URL
        encoded_prompt = urllib.parse.quote(full_prompt)
        
        # Новый эндпоинт (text.pollinations.ai/PROMPT)
        url = f"https://text.pollinations.ai/{encoded_prompt}?model=openai&seed={random.randint(1, 1000)}"
        
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.text
                else:
                    logger.error(f"Pollinations HTTP {resp.status_code}")
        except Exception as e:
            logger.error(f"Pollinations Exception: {e}")
        return ""

    @staticmethod
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        system_prompt = get_system_prompt(mode)
        
        messages = [{"role": "system", "content": system_prompt}]
        for msg in history:
            messages.append(msg)
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        # ЗАПРОС К ИИ
        response_text = await ChatManager.ask_pollinations(messages)

        # Резерв
        if not response_text:
            response_text = "Связь с космосом прервана... 🛸"
        else:
            response_text = ChatManager.clean_response(response_text)

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text
