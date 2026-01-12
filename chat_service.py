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
        try:
            auth_headers = {
                "Authorization": f"Bearer {provider.api_key}" if not provider.api_key.startswith("Basic") else provider.api_key,
                "RqUID": str(uuid.uuid4()),
                "Content-Type": "application/x-www-form-urlencoded"
            }
            if " " not in auth_headers["Authorization"]:
                auth_headers["Authorization"] = f"Basic {provider.api_key}"

            token_resp = await client.post(
                "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
                data={"scope": "GIGACHAT_API_PERS"},
                headers=auth_headers,
                verify=False,
                timeout=5.0
            )
            if token_resp.status_code != 200: 
                logger.warning(f"[GigaChat] Auth Fail: {token_resp.status_code}") # Added logging
                return None
            access_token = token_resp.json()["access_token"]

            chat_resp = await client.post(
                f"{provider.base_url}/chat/completions",
                json={"model": provider.model, "messages": messages, "max_tokens": 150},
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                verify=False,
                timeout=8.0 # Changed timeout from 10.0 to 8.0
            )
            if chat_resp.status_code == 200: 
                return chat_resp.json()["choices"][0]["message"]["content"]
            else:
                logger.warning(f"[GigaChat] Chat Fail: {chat_resp.status_code}") # Added logging
        except Exception as e: # Catch specific exception
            logger.error(f"[GigaChat] Error: {e}") # Changed to error
        return None

    @staticmethod
    async def _call_generic(client: httpx.AsyncClient, provider: AIProviderConfig, messages: list) -> str:
        try:
            headers = {"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"}
            payload = {"model": provider.model, "messages": messages, "max_tokens": 150}
            
            resp = await client.post(provider.base_url, json=payload, headers=headers, timeout=6.0) # Changed timeout from 8.0 to 6.0
            if resp.status_code == 200:
                data = resp.json()
                if "choices" in data: return data["choices"][0]["message"]["content"]
                if isinstance(data, list) and "generated_text" in data[0]: return data[0]["generated_text"]
            else:
                logger.warning(f"[{provider.name}] Status {resp.status_code}: {resp.text[:100]}") # Added logging
        except Exception as e: # Catch specific exception
            logger.warning(f"[{provider.name}] Error: {e}") # Changed to error
        return None

    @staticmethod
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        messages = [{"role": "system", "content": PERSONAS.get(mode, "")}]
        for msg in history: messages.append(msg)
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        # 1. Providers
        async with httpx.AsyncClient(verify=False) as http_client:
            for provider in get_active_providers():
                res = None
                if provider.name == "GigaChat":
                    res = await ChatManager._call_gigachat(http_client, provider, messages)
                else:
                    res = await ChatManager._call_generic(http_client, provider, messages)
                
                if res and res.strip(): # Проверка на пустую строку
                    history.append({"role": "user", "content": user_text})
                    history.append({"role": "assistant", "content": res})
                    return res

        # 2. Native Gemini
        full_prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
        loop = asyncio.get_event_loop()
        if res := await loop.run_in_executor(None, lambda: generate_smart(full_prompt)):
            if res and res.strip():
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": res})
                return res

        # 3. GARANTEED FALLBACK (Никогда не возвращаем None)
        return "Сигнал нестабилен, но я тебя слышу! 📡"