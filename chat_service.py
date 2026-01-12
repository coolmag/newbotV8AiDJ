import logging
import random
import uuid
import httpx
import asyncio
from collections import deque, defaultdict

from ai_config import get_active_providers, AIProviderConfig
from gemini_init import generate_smart

logger = logging.getLogger(__name__)

chat_histories = defaultdict(lambda: deque(maxlen=6))
chat_modes = defaultdict(lambda: "default")

PERSONAS = {
    "default": "Ты DJ Aurora. Веселая, используй эмодзи.",
    "toxic": "Ты DJ Aurora (Toxic).",
    "gop": "Ты Аврора с района.",
    "chill": "Ты Аврора (Chill).",
    "quiz": "Ты Ведущая Викторины."
}

class ChatManager:
    @staticmethod
    def set_mode(chat_id: int, mode: str): chat_modes[chat_id] = mode
    @staticmethod
    def get_mode(chat_id: int): return chat_modes[chat_id]

    @staticmethod
    async def _call_gigachat(client: httpx.AsyncClient, provider: AIProviderConfig, messages: list) -> str:
        """Авторизация и запрос к GigaChat"""
        try:
            # 1. Auth
            auth_headers = {
                "Authorization": f"Bearer {provider.api_key}" if not provider.api_key.startswith("Basic") else provider.api_key,
                "RqUID": str(uuid.uuid4()),
                "Content-Type": "application/x-www-form-urlencoded"
            }
            # Если ключ без префикса, добавляем Basic (частая ошибка)
            if " " not in auth_headers["Authorization"]:
                auth_headers["Authorization"] = f"Basic {provider.api_key}"

            token_resp = await client.post(
                "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
                data={"scope": "GIGACHAT_API_PERS"},
                headers=auth_headers,
                verify=False, # Сбер использует свои сертификаты
                timeout=5.0
            )
            
            if token_resp.status_code != 200:
                logger.warning(f"[GigaChat] Auth Fail: {token_resp.status_code}")
                return None
            
            access_token = token_resp.json()["access_token"]

            # 2. Chat
            chat_resp = await client.post(
                f"{provider.base_url}/chat/completions",
                json={"model": provider.model, "messages": messages, "max_tokens": 150},
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                verify=False,
                timeout=10.0
            )
            
            if chat_resp.status_code == 200:
                return chat_resp.json()["choices"][0]["message"]["content"]
            
        except Exception as e:
            logger.error(f"[GigaChat] Error: {e}")
        return None

    @staticmethod
    async def _call_generic(client: httpx.AsyncClient, provider: AIProviderConfig, messages: list) -> str:
        """OpenAI-compatible call (HF, Groq, etc)"""
        try:
            headers = {"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"}
            payload = {"model": provider.model, "messages": messages, "max_tokens": 150}
            
            # Фикс для HF Router: иногда он не любит поле model в теле, если оно есть в URL
            # Но OpenAI стандарт требует его. Оставим как есть, обычно работает.
            
            resp = await client.post(provider.base_url, json=payload, headers=headers, timeout=8.0)
            
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            
            logger.warning(f"[{provider.name}] Status {resp.status_code}: {resp.text[:100]}")
        except Exception as e:
            logger.warning(f"[{provider.name}] Error: {e}")
        return None

    @staticmethod
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        messages = [{"role": "system", "content": PERSONAS.get(mode, "")}]
        for msg in history: messages.append(msg)
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        async with httpx.AsyncClient(verify=False) as http_client:
            # Перебираем провайдеров
            for provider in get_active_providers():
                res = None
                if provider.name == "GigaChat":
                    res = await ChatManager._call_gigachat(http_client, provider, messages)
                else:
                    res = await ChatManager._call_generic(http_client, provider, messages)
                
                if res:
                    history.append({"role": "user", "content": user_text})
                    history.append({"role": "assistant", "content": res})
                    return res

        # Fallback Gemini (если и Сбер упал)
        full_prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
        loop = asyncio.get_event_loop()
        if res := await loop.run_in_executor(None, lambda: generate_smart(full_prompt)):
            return res

        return "Абонент временно недоступен, но музыка вечна! 🎧"
