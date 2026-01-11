import logging
import os
import random
import re
import json
from collections import deque, defaultdict
import asyncio
import httpx # Для прямых запросов к DuckDuckGo

# GIGACHAT IMPORT
try:
    from gigachat import GigaChat
    HAS_GIGACHAT = True
except ImportError:
    HAS_GIGACHAT = False

import g4f
from g4f.client import Client as G4FClient
from ai_personas import get_system_prompt, PERSONAS

logger = logging.getLogger(__name__)

chat_histories = defaultdict(lambda: deque(maxlen=10))
chat_modes = defaultdict(lambda: "default")

OFFLINE_ANSWERS = {
    "default": [
        "Связь с космосом барахлит, но музыка играет! 🎧",
        "Мои нейроны перезагружаются, лови ритм!",
        "Что-то интернет лагает, давай лучше танцевать!"
    ],
    "toxic": ["Отвали, я занята.", "Пинг высокий, иди гуляй."],
    "gop": ["Слыш, связь плохая.", "Че сказал? Не слышу."]
}

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
        junk = ["GigaChat", "Сбер", "AI language model", "OpenAI", "DuckDuckGo"]
        for phrase in junk:
            text = re.sub(f"(?i){phrase}", "Aurora", text)
        return text.strip()

    # --- DUCKDUCKGO DIRECT API (STABLE FREE) ---
    @staticmethod
    async def ask_duckduckgo(messages: list) -> str:
        url = "https://duckduckgo.com/duckchat/v1/chat"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://duckduckgo.com/",
            "x-vqd-accept": "1"
        }
        
        try:
            async with httpx.AsyncClient() as client:
                # 1. Get Token
                status = await client.get("https://duckduckgo.com/duckchat/v1/status", headers=headers)
                token = status.headers.get("x-vqd-4")
                if not token: return ""

                # 2. Chat
                chat_headers = headers.copy()
                chat_headers["x-vqd-4"] = token
                chat_headers["Content-Type"] = "application/json"
                
                # Формируем промпт
                system_msg = messages[0]["content"]
                last_msg = messages[-1]["content"]
                
                payload = {
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "user", "content": f"{system_msg}\n\nUser: {last_msg}"}
                    ]
                }
                
                resp = await client.post(url, headers=chat_headers, json=payload)
                if resp.status_code == 200:
                    # Ответ приходит как event-stream, берем текст
                    text = resp.text
                    # Ищем поле message
                    matches = re.findall(r'"message":"(.*?)"', text)
                    if matches:
                        # Собираем куски (stream)
                        full_text = "".join(matches).replace(r'\n', '\n')
                        return full_text
        except Exception as e:
            logger.error(f"DDG Error: {e}")
        return ""

    @staticmethod
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        
        system_instruction = get_system_prompt(mode)
        
        messages = [{"role": "system", "content": system_instruction}]
        for msg in history: messages.append(msg)
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        response_text = ""
        
        # 1. GIGACHAT (Если есть ключ)
        giga_key = os.getenv("GIGACHAT_CREDENTIALS")
        if HAS_GIGACHAT and giga_key:
            try:
                def ask_sber():
                    with GigaChat(credentials=giga_key, scope="GIGACHAT_API_PERS", verify_ssl_certs=False) as giga:
                        return giga.chat(messages).choices[0].message.content
                response_text = await asyncio.get_running_loop().run_in_executor(None, ask_sber)
            except Exception as e:
                logger.error(f"GigaChat Error: {e}")

        # 2. DUCKDUCKGO (Бесплатный резерв)
        if not response_text:
            response_text = await ChatManager.ask_duckduckgo(messages)

        # 3. G4F (Последний шанс)
        if not response_text:
            try:
                def ask_g4f():
                    client = G4FClient()
                    return client.chat.completions.create(
                        model=g4f.models.gpt_4o_mini,
                        messages=messages
                    ).choices[0].message.content
                response_text = await asyncio.get_running_loop().run_in_executor(None, ask_g4f)
            except: pass

        # 4. FALLBACK
        if not response_text:
            answers = OFFLINE_ANSWERS.get(mode, OFFLINE_ANSWERS["default"])
            response_text = random.choice(answers)
        else:
            response_text = ChatManager.clean_response(response_text)

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text