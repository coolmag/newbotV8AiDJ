import logging
import random
import uuid
import json
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
    "toxic": "Ты DJ Aurora (Toxic). Хами.",
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
        """Специальная логика для GigaChat (Авторизация + Запрос)"""
        try:
            # 1. Получаем токен доступа (OAuth)
            auth_url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
            auth_headers = {
                "Authorization": f"Bearer {provider.api_key}", # Если ключ не Basic, заменить на Basic
                "RqUID": str(uuid.uuid4()),
                "Content-Type": "application/x-www-form-urlencoded"
            }
            # Обычно GIGACHAT_CREDENTIALS это уже Base64 для Basic Auth. 
            # Если в логах ошибка 401, значит надо добавить 'Basic ' вручную.
            if not provider.api_key.startswith("Basic ") and not provider.api_key.startswith("Bearer "):
                 auth_headers["Authorization"] = f"Basic {provider.api_key}"

            # Отключаем verify=False, т.к. сертификаты МинЦифры могут отсутствовать
            token_resp = await client.post(auth_url, data={"scope": "GIGACHAT_API_PERS"}, headers=auth_headers, verify=False, timeout=5.0)
            
            if token_resp.status_code != 200:
                logger.warning(f"[GigaChat] Auth fail: {token_resp.text}")
                return None
                
            access_token = token_resp.json().get("access_token")

            # 2. Делаем запрос к чату
            chat_url = f"{provider.base_url}/chat/completions"
            chat_headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": provider.model,
                "messages": messages,
                "max_tokens": 150
            }
            
            chat_resp = await client.post(chat_url, json=payload, headers=chat_headers, verify=False, timeout=8.0)
            
            if chat_resp.status_code == 200:
                return chat_resp.json()["choices"][0]["message"]["content"]
            else:
                logger.warning(f"[GigaChat] Chat error: {chat_resp.text}")

        except Exception as e:
            logger.error(f"[GigaChat] Exception: {e}")
        return None

    @staticmethod
    async def _call_generic(client: httpx.AsyncClient, provider: AIProviderConfig, messages: list) -> str:
        """Обычный вызов для OpenAI-совместимых API (Groq, Novita, HF, OpenRouter)"""
        try:
            headers = {"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"}
            payload = {"model": provider.model, "messages": messages, "max_tokens": 150}
            
            # HuggingFace костыль для Inference API
            if "huggingface" in provider.base_url:
                payload.pop("model", None)
            
            resp = await client.post(provider.base_url, json=payload, headers=headers, timeout=6.0)
            
            if resp.status_code == 200:
                data = resp.json()
                if "choices" in data: return data["choices"][0]["message"]["content"]
                if isinstance(data, list) and "generated_text" in data[0]: return data[0]["generated_text"]
            
            logger.warning(f"[{provider.name}] Error {resp.status_code}")
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

        # Fallback: Native Gemini
        full_prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
        loop = asyncio.get_event_loop()
        if res := await loop.run_in_executor(None, lambda: generate_smart(full_prompt)):
            return res

        # Fallback: Local
        return "Сигнал слабый, но я тут! 🎧 (Все нейросети спят)"