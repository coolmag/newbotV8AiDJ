import logging
import random
import re
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
        junk = ["Pollinations", "OpenAI", "ChatGPT", "AI model", "language model", "Mistral"]
        for phrase in junk:
            text = re.sub(f"(?i){phrase}", "Aurora", text)
        return text.strip()

    # --- POLLINATIONS BYPASS 2026 ---
    @staticmethod
    async def ask_pollinations(messages: list) -> str:
        full_prompt = ""
        for msg in messages:
            full_prompt += f"{msg['role']}: {msg['content']}\n"
        
        encoded_prompt = urllib.parse.quote(full_prompt)
        
        # MISTRAL (Менее загруженная модель) + SEED
        url = f"https://text.pollinations.ai/{encoded_prompt}?model=mistral&seed={random.randint(1, 99999)}"
        
        # Заголовки для имитации браузера
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*"
        }
        
        try:
            async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.text
                else:
                    logger.warning(f"Pollinations Block: {resp.status_code}")
        except: pass
        return ""

    @staticmethod
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        system_prompt = get_system_prompt(mode)
        
        messages = [{"role": "system", "content": system_prompt}]
        for msg in history:
            messages.append(msg)
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        # ЗАПРОС
        response_text = await ChatManager.ask_pollinations(messages)

        # РЕЗЕРВ (Если забанили IP)
        if not response_text:
            backups = [
                "Связь с космосом прервана... 🛸",
                "Мои серверы перегрелись от твоей крутости! 🔥",
                "Что-то помехи в эфире, повтори?",
                "Аврора на связи! (ИИ перезагружается)"
            ]
            response_text = random.choice(backups)
        else:
            response_text = ChatManager.clean_response(response_text)

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text
