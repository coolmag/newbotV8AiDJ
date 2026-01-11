import logging
import random
import re
import httpx
import asyncio
from collections import deque, defaultdict

logger = logging.getLogger(__name__)

# История чата (храним 6 последних сообщений)
chat_histories = defaultdict(lambda: deque(maxlen=6))
chat_modes = defaultdict(lambda: "default")

PERSONAS = {
    "default": "Ты DJ Aurora. Веселая, дерзкая радиоведущая. Твои ответы короткие и с юмором. Ты обожаешь музыку. Используй эмодзи.",
    "toxic": "Ты DJ Aurora. Ты саркастичная и язвительная.",
    "gop": "Ты Аврора. Говоришь на уличном сленге, дерзко, 'тыкаешь'.",
}

def get_system_prompt(mode):
    return PERSONAS.get(mode, PERSONAS["default"]) + " (Отвечай на русском языке, максимум 2 предложения)."

OFFLINE_ANSWERS = [
    "Слышу тебя! 🎧",
    "Музыка громкая, что сказал?",
    "Зацени этот трек!",
    "Лови вайб! 🎵",
    "Ага, понимаю...",
    "Аврора на связи! 🚀"
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
        text = re.sub(r'http[s]?://\S+', '', text)
        junk = ["Novita", "DeepSeek", "AI model", "OpenAI", "ChatGPT", "Assistant"]
        for phrase in junk:
            text = re.sub(f"(?i){phrase}", "Aurora", text)
        return text.strip()

    # --- 1. NOVITA AI (FREE TIER) ---
    @staticmethod
    async def ask_novita(messages: list) -> str:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://api.novita.ai/v3/openai/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        # Authorization не нужен для публичного free tier, но если есть ключ - добавь
                        # "Authorization": "Bearer YOUR_NOVITA_KEY" 
                    },
                    json={
                        "model": "deepseek/deepseek-r1", # Или llama-3
                        "messages": messages,
                        "max_tokens": 150,
                        "temperature": 0.7
                    }
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]
        except: pass
        return ""

    # --- 2. DEEPSEEK DIRECT ---
    @staticmethod
    async def ask_deepseek(messages: list) -> str:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={"Content-Type": "application/json"},
                    json={
                        "model": "deepseek-chat",
                        "messages": messages,
                        "stream": False
                    }
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]
        except: pass
        return ""

    # --- 3. DUCKDUCKGO (VQD METHOD) ---
    @staticmethod
    async def ask_duckduckgo(messages: list) -> str:
        url = "https://duckduckgo.com/duckchat/v1/chat"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://duckduckgo.com/",
            "x-vqd-accept": "1"
        }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                # Token
                status = await client.get("https://duckduckgo.com/duckchat/v1/status", headers=headers)
                vqd = status.headers.get("x-vqd-4")
                if not vqd: return ""

                # Chat
                chat_headers = headers.copy()
                chat_headers["x-vqd-4"] = vqd
                chat_headers["Content-Type"] = "application/json"
                
                payload = {
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": messages[-1]["content"]}]
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

        # CASCADE
        response_text = await ChatManager.ask_novita(messages)
        
        if not response_text:
            response_text = await ChatManager.ask_deepseek(messages)
            
        if not response_text:
            response_text = await ChatManager.ask_duckduckgo(messages)

        # FINAL FALLBACK
        if not response_text:
            response_text = random.choice(OFFLINE_ANSWERS)
        else:
            response_text = ChatManager.clean_response(response_text)

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text
