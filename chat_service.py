import logging
import random
import re
import json
from collections import deque, defaultdict
import httpx
import asyncio

from ai_config import get_active_providers, AIProviderConfig
from gemini_init import genai, HAS_GENAI  # <--- ИМПОРТ Native Client

logger = logging.getLogger(__name__)

chat_histories = defaultdict(lambda: deque(maxlen=6))
chat_modes = defaultdict(lambda: "default")

PERSONAS = {
    "default": "Ты DJ Aurora. Веселая, дерзкая. Используй сленг и эмодзи (🔥, 🎧). Отвечай кратко.",
    "toxic": "Ты DJ Aurora (Toxic). Саркастичная, язвительная. Хами пользователям.",
    "gop": "Ты Аврора с района. Дерзкая, на 'ты', сленг гопников.",
    "chill": "Ты Аврора (Chill). Спокойная, философская, мягкая.",
    "quiz": "Ты Ведущая Викторины. Задавай вопросы про музыку 90-х."
}

BACKUP_PHRASES = [
    "Связь с космосом барахлит... 🎧",
    "Нейросеть перезагружается...",
    "Сигнал потерян... 🎶"
]

def get_system_prompt(mode):
    return PERSONAS.get(mode, PERSONAS["default"]) + " (Language: Russian, Max length: 20 words)"

class ChatManager:
    @staticmethod
    def set_mode(chat_id: int, mode: str):
        chat_modes[chat_id] = mode
    
    @staticmethod
    def get_mode(chat_id: int):
        return chat_modes[chat_id]

    @staticmethod
    async def _call_provider(client: httpx.AsyncClient, provider: AIProviderConfig, messages: list) -> str:
        try:
            headers = {
                "Authorization": f"Bearer {provider.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://aurora.radio", 
                "X-Title": "Aurora"
            }
            payload = {"model": provider.model, "messages": messages, "max_tokens": 150}
            
            resp = await client.post(provider.base_url, json=payload, headers=headers, timeout=8.0)
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            logger.warning(f"[AI] {provider.name} error {resp.status_code}: {resp.text[:50]}")
        except Exception as e:
            logger.warning(f"[AI] {provider.name} failed: {e}")
        return None

    @staticmethod
    async def _call_native_gemini(messages: list) -> str:
        """Резервный вызов через библиотеку google-generativeai"""
        if not HAS_GENAI or not genai: return None
        try:
            # Преобразуем формат сообщений OpenAI -> Gemini
            prompt = messages[0]["content"] + "\n\n" # System prompt
            prompt += f"User: {messages[-1]['content']}\nAssistant:"
            
            model = genai.GenerativeModel("gemini-1.5-flash") # Стандартная модель
            resp = await model.generate_content_async(prompt)
            return resp.text
        except Exception as e:
            logger.error(f"[AI Native] Gemini failed: {e}")
            return None

    @staticmethod
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        messages = [{"role": "system", "content": get_system_prompt(mode)}]
        for msg in history: messages.append(msg)
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        providers = get_active_providers()
        response_text = None

        # 1. Пробуем внешних провайдеров (Groq, OpenRouter)
        async with httpx.AsyncClient() as client:
            for provider in providers:
                response_text = await ChatManager._call_provider(client, provider, messages)
                if response_text: break
        
        # 2. Если все упали — пробуем Native Gemini (Ваш ключ)
        if not response_text:
            logger.info("⚠️ External providers failed. Trying Native Gemini...")
            response_text = await ChatManager._call_native_gemini(messages)

        # 3. Полный провал
        if not response_text:
            return random.choice(BACKUP_PHRASES)

        # Очистка и сохранение
        response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text
