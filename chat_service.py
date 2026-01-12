import logging
import random
import re
import json
from collections import deque, defaultdict
import httpx
import asyncio

# Импортируем нашу новую логику конфигов
from ai_config import get_active_providers, AIProviderConfig

logger = logging.getLogger(__name__)

# Хранилище истории диалогов
chat_histories = defaultdict(lambda: deque(maxlen=6))
chat_modes = defaultdict(lambda: "default")

PERSONAS = {
    "default": "Ты DJ Aurora. Веселая и дерзкая. Если просят музыку - отвечай JSON: {\"command\": \"radio\", \"query\": \"жанр\"}. Иначе - текст (до 20 слов).",
    "toxic": "Ты DJ Aurora (Toxic). Дерзкая. Отвечай коротко и язвительно.",
    "gop": "Ты — Аврора с района. Общаешься дерзко, на 'ты', используешь уличный жаргон.",
    "chill": "Ты — DJ Aurora на ночном эфире. Спокойная, загадочная, философская.",
    "quiz": "Ты — Ведущая Викторины Аврора."
}

BACKUP_PHRASES = [
    "Связь с космосом барахлит, но музыка играет! 🎧",
    "Аврора на связи! (Нейросеть перезагружается, секунду...)",
    "Что-то интернет лагает, давай просто послушаем музыку? 🎶",
    "Мои схемы перегрелись от твоего запроса! 🔥",
    "Сигнал потерян... Ищу волну..."
]

def get_system_prompt(mode):
    return PERSONAS.get(mode, PERSONAS["default"]) + " (Language: Russian)"

class ChatManager:
    @staticmethod
    def set_mode(chat_id: int, mode: str) -> bool:
        chat_modes[chat_id] = mode
        return True
    
    @staticmethod
    def get_mode(chat_id: int) -> str:
        return chat_modes[chat_id]

    @staticmethod
    async def _request_provider(client: httpx.AsyncClient, provider: AIProviderConfig, messages: list) -> str:
        """Попытка запроса к конкретному провайдеру."""
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://aurora.radio",
        }
        
        payload = {
            "model": provider.model,
            "messages": messages,
            "max_tokens": 250,
            "temperature": 0.8
        }

        try:
            response = await client.post(provider.base_url, json=payload, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return content
            else:
                logger.warning(f"[AI] {provider.name} Error: {response.status_code} - {response.text[:100]}")
                return ""
        except Exception as e:
            logger.warning(f"[AI] {provider.name} Connection Failed: {e}")
            return ""

    @staticmethod
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        system_prompt = get_system_prompt(mode)
        
        # Формируем контекст
        messages = [{"role": "system", "content": system_prompt}]
        for msg in history: 
            messages.append(msg)
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        response_text = ""
        providers = get_active_providers()
        
        # --- CASCADE LOGIC ---
        if not providers:
            logger.error("[AI] No active AI providers configured (Check .env)")
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            for provider in providers:
                # Пробуем каждого провайдера по очереди
                response_text = await ChatManager._request_provider(client, provider, messages)
                if response_text:
                    logger.info(f"[AI] Success via {provider.name}")
                    break
        
        # Если все провайдеры упали или нет ключей
        if not response_text:
            logger.error("[AI] All providers failed. Using backup phrase.")
            response_text = random.choice(BACKUP_PHRASES)

        # Очистка от <think> тегов (DeepSeek/R1)
        response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()
        
        # Обработка JSON команд (если ИИ решил включить музыку)
        if "command" in response_text and "{" in response_text:
            # Не сохраняем технические команды в историю, чтобы не засорять контекст
            return response_text 

        # Сохраняем в историю
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text
