import logging
import random
import re
import json
from collections import deque, defaultdict
import httpx
import asyncio

# Подключаем нашу новую конфигурацию
from ai_config import get_active_providers, AIProviderConfig

logger = logging.getLogger(__name__)

# Храним последние 6 сообщений для контекста
chat_histories = defaultdict(lambda: deque(maxlen=6))
chat_modes = defaultdict(lambda: "default")

PERSONAS = {
    "default": "Ты DJ Aurora. Веселая и дерзкая. Твоя задача - развлекать и ставить музыку. Если просят включить музыку, отвечай строго JSON форматом: {\"command\": \"radio\", \"query\": \"жанр или исполнитель\"}. Если просто болтают - отвечай текстом (до 20 слов), используй молодежный сленг и эмодзи (🔥, 🎧).",
    "toxic": "Ты DJ Aurora (Toxic Mode). Ты язвительная, саркастичная и дерзкая. Музыкальный вкус у людей ужасный, и ты не стесняешься об этом говорить. Отвечай коротко и хлестко.",
    "gop": "Ты — Аврора с района. Общаешься дерзко, на 'ты', используешь уличный жаргон. Любишь басы и четкую музыку.",
    "chill": "Ты — DJ Aurora на ночном эфире. Голос спокойный, мягкий, немного философский. Тема: космос, релакс, вайб.",
    "quiz": "Ты — Ведущая Викторины. Задавай вопросы о музыке 90-х и 00-х."
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
    async def _call_provider(client: httpx.AsyncClient, provider: AIProviderConfig, messages: list) -> str:
        """Попытка запроса к конкретному провайдеру"""
        try:
            headers = {
                "Authorization": f"Bearer {provider.api_key}",
                "Content-Type": "application/json",
                # Некоторые API (OpenRouter) требуют эти заголовки
                "HTTP-Referer": "https://aurora.radio", 
                "X-Title": "Aurora Player"
            }
            
            payload = {
                "model": provider.model,
                "messages": messages,
                "max_tokens": 200,
                "temperature": 0.85
            }

            # Таймаут 10 секунд на одного провайдера
            response = await client.post(provider.base_url, json=payload, headers=headers, timeout=10.0)
            
            if response.status_code == 200:
                data = response.json()
                # Стандартный формат OpenAI ответа
                if "choices" in data and len(data["choices"]) > 0:
                    content = data["choices"][0]["message"]["content"]
                    return content
            
            logger.warning(f"[AI] {provider.name} failed with status {response.status_code}: {response.text[:100]}")
        except Exception as e:
            logger.warning(f"[AI] {provider.name} connection error: {e}")
        
        return None

    @staticmethod
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        system_prompt = get_system_prompt(mode)
        
        # Формируем историю сообщений
        messages = [{"role": "system", "content": system_prompt}]
        for msg in history:
            messages.append(msg)
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        providers = get_active_providers()
        response_text = None

        if not providers:
            logger.error("[AI] No active providers configured! Check .env variables.")
            return random.choice(BACKUP_PHRASES)

        # === CASCADE LOGIC ===
        # Перебираем провайдеров, пока один из них не ответит
        async with httpx.AsyncClient() as client:
            for provider in providers:
                # logger.info(f"[AI] Trying {provider.name}...") 
                response_text = await ChatManager._call_provider(client, provider, messages)
                if response_text:
                    logger.info(f"[AI] Success via {provider.name}")
                    break
        
        # Если ВСЕ провайдеры упали
        if not response_text:
            logger.error("[AI] All providers failed.")
            return random.choice(BACKUP_PHRASES)

        # Очистка от "мыслей" (DeepSeek R1 иногда выдает <think>)
        response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()
        
        # Логика обработки команд JSON (если бот хочет включить музыку)
        if "command" in response_text and "{" in response_text:
            # Не сохраняем технические команды в историю
            return response_text 

        # Сохраняем успешный диалог в историю
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text