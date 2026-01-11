import logging
import os
import random
import re
import json
import uuid
import time
from collections import deque, defaultdict
import asyncio
import httpx # Используем только надежный HTTP клиент

logger = logging.getLogger(__name__)

# Память контекста
chat_histories = defaultdict(lambda: deque(maxlen=6)) # Храним 6 последних фраз (оптимизация)
chat_modes = defaultdict(lambda: "default")

# Промпты (Личности)
PERSONAS = {
    "default": "Ты DJ Aurora. Веселая, дерзкая, любишь музыку. Отвечай кратко, используй эмодзи.",
    "toxic": "Ты DJ Aurora. Саркастичная, язвительная. Тебе не нравятся глупые вопросы.",
    "gop": "Ты Аврора с района. Дерзкая, используешь сленг, любишь басы.",
    "chill": "Ты Аврора на ночном эфире. Спокойная, загадочная, философская.",
    "quiz": "Ты ведущая викторины. Задавай вопросы про музыку."
}

def get_system_prompt(mode):
    return PERSONAS.get(mode, PERSONAS["default"]) + " Отвечай на русском. Не более 2 предложений."

# Резервные ответы (Offline)
FALLBACKS = [
    "Связь с космосом прервана, но я тут! 🎧",
    "Мои нейроны перегрелись, давай лучше музыку послушаем.",
    "Что-то интернет тормозит, повтори?",
    "Аврора на связи! (ИИ перезагружается ⚙️)"
]

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
        # Убираем ссылки и рекламные теги
        text = re.sub(r'http\S+', '', text)
        text = re.sub(r'\[.*?\]', '', text)
        junk = ["GigaChat", "Сбер", "OpenAI", "ChatGPT", "DuckDuckGo", "AI model"]
        for phrase in junk:
            text = re.sub(f"(?i){phrase}", "Aurora", text)
        return text.strip()

    # --- 1. GIGACHAT DIRECT API (Самый надежный метод) ---
    @staticmethod
    async def ask_gigachat_api(messages: list) -> str:
        auth_data = os.getenv("GIGACHAT_CREDENTIALS")
        if not auth_data: return ""

        try:
            # Генерация UUID для requestId
            rq_uid = str(uuid.uuid4())
            
            async with httpx.AsyncClient(verify=False, timeout=5.0) as client:
                # 1. Получаем токен (OAuth)
                token_resp = await client.post(
                    "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
                    headers={
                        "Authorization": f"Basic {auth_data}",
                        "RqUID": rq_uid,
                        "Content-Type": "application/x-www-form-urlencoded"
                    },
                    data={"scope": "GIGACHAT_API_PERS"}
                )
                
                if token_resp.status_code != 200:
                    logger.warning(f"GigaChat Auth Failed: {token_resp.status_code}")
                    return ""
                
                access_token = token_resp.json()["access_token"]

                # 2. Запрос к модели
                chat_resp = await client.post(
                    "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {access_token}"},
                    json={
                        "model": "GigaChat",
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 100
                    }
                )
                
                if chat_resp.status_code == 200:
                    return chat_resp.json()["choices"][0]["message"]["content"]
                
        except Exception as e:
            logger.error(f"GigaChat Direct Error: {e}")
        return ""

    # --- 2. DUCKDUCKGO (Резерв) ---
    @staticmethod
    async def ask_duckduckgo(messages: list) -> str:
        try:
            # Формируем простой контекст
            prompt = "\n".join([m["content"] for m in messages])
            
            async with httpx.AsyncClient(timeout=8.0) as client:
                # Получаем VQD
                init = await client.get("https://duckduckgo.com/duckchat/v1/status", headers={"x-vqd-accept": "1"})
                vqd = init.headers.get("x-vqd-4")
                if not vqd: return ""

                # Чат
                resp = await client.post(
                    "https://duckduckgo.com/duckchat/v1/chat",
                    headers={
                        "x-vqd-4": vqd,
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [{"role": "user", "content": prompt}]
                    }
                )
                
                if resp.status_code == 200:
                    # Простой парсинг SSE
                    full_text = ""
                    for line in resp.text.split('\n'):
                        if 'message":"' in line:
                            match = re.search(r'"message":"(.*?)"', line)
                            if match: full_text += match.group(1).replace("\n", "\n")
                    return full_text
        except Exception as e:
            logger.warning(f"DDG Error: {e}")
        return ""

    @staticmethod
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        
        system_prompt = get_system_prompt(mode)
        
        # Формируем структуру сообщений для API
        api_messages = [{"role": "system", "content": system_prompt}]
        for msg in history:
            api_messages.append({"role": msg["role"], "content": msg["content"]})
        api_messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        response_text = ""

        # СТРАТЕГИЯ:
        # 1. Пробуем GigaChat (быстро и надежно)
        # 2. Если нет - DuckDuckGo (бесплатно)
        # 3. Если нет - Заглушка (мгновенно)
        
        # Шаг 1
        if os.getenv("GIGACHAT_CREDENTIALS"):
            response_text = await ChatManager.ask_gigachat_api(api_messages)
        
        # Шаг 2
        if not response_text:
            response_text = await ChatManager.ask_duckduckgo(api_messages)

        # Шаг 3 (Финал)
        if not response_text:
            response_text = random.choice(FALLBACKS)
        else:
            response_text = ChatManager.clean_response(response_text)

        # Сохраняем в историю
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text
