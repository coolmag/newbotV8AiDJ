import logging
import random
import re
import json
import urllib.parse
from collections import deque, defaultdict
import asyncio
import httpx 

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
        junk = ["Pollinations", "OpenAI", "ChatGPT", "AI model", "Mistral", "language model"]
        for phrase in junk:
            text = re.sub(f"(?i){phrase}", "Aurora", text)
        return text.strip()

    # --- 1. POLLINATIONS (MISTRAL MODE) ---
    @staticmethod
    async def ask_pollinations(messages: list) -> str:
        full_prompt = ""
        for msg in messages:
            full_prompt += f"{msg['role']}: {msg['content']}\n"
        
        encoded_prompt = urllib.parse.quote(full_prompt)
        
        # MISTRAL (Менее загружена)
        url = f"https://text.pollinations.ai/{encoded_prompt}?model=mistral&seed={random.randint(1, 1000)}"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        try:
            async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
                resp = await client.get(url)
                if resp.status_code == 200: return resp.text
                else: logger.warning(f"Pollinations Status: {resp.status_code}")
        except: pass
        return ""

    # --- 2. DUCKDUCKGO (BACKUP) ---
    @staticmethod
    async def ask_duckduckgo(messages: list) -> str:
        url = "https://duckduckgo.com/duckchat/v1/chat"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://duckduckgo.com/",
            "x-vqd-accept": "1"
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                status = await client.get("https://duckduckgo.com/duckchat/v1/status", headers=headers)
                token = status.headers.get("x-vqd-4")
                if not token: return ""

                chat_headers = headers.copy()
                chat_headers["x-vqd-4"] = token
                chat_headers["Content-Type"] = "application/json"
                
                system_prompt = messages[0]["content"]
                last_msg = messages[-1]["content"]
                
                payload = {
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": f"{system_prompt}\n\nUser: {last_msg}"}]
                }
                
                resp = await client.post(url, headers=chat_headers, json=payload)
                if resp.status_code == 200:
                    data = resp.text
                    matches = re.findall(r'"message":"(.*?)"', data)
                    if matches: return "".join(matches).replace(r'\n', '\n')
        except: pass
        return ""

    @staticmethod
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        system_prompt = get_system_prompt(mode)
        
        messages = [{"role": "system", "content": system_prompt}]
        for msg in history: messages.append(msg)
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        # TRY 1
        response_text = await ChatManager.ask_pollinations(messages)

        # TRY 2
        if not response_text:
            response_text = await ChatManager.ask_duckduckgo(messages)

        # TRY 3
        if not response_text:
            response_text = "Связь с космосом прервана... 🛸"
        else:
            response_text = ChatManager.clean_response(response_text)

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text