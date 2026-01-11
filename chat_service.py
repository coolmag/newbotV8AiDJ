import logging
import random
import re
import json
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
        chat_modes[chat_id] = mode
        chat_histories[chat_id].clear()
        return True

    @staticmethod
    def clean_response(text: str) -> str:
        if not text: return ""
        text = re.sub(r'http[s]?://\S+', '', text)
        junk = ["OpenAI", "ChatGPT", "Claude", "DuckDuckGo", "AI model", "language model"]
        for phrase in junk:
            text = re.sub(f"(?i){phrase}", "Aurora", text)
        return text.strip()

    # --- DUCKDUCKGO (The Reliable Choice) ---
    @staticmethod
    async def ask_duckduckgo(messages: list) -> str:
        # Эндпоинт чата
        url_status = "https://duckduckgo.com/duckchat/v1/status"
        url_chat = "https://duckduckgo.com/duckchat/v1/chat"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://duckduckgo.com/",
            "x-vqd-accept": "1"
        }
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # 1. Получаем токен сессии (VQD)
                status_resp = await client.get(url_status, headers=headers)
                vqd = status_resp.headers.get("x-vqd-4")
                
                if not vqd: return ""

                # 2. Шлем сообщение
                chat_headers = headers.copy()
                chat_headers["x-vqd-4"] = vqd
                chat_headers["Content-Type"] = "application/json"
                
                # Формируем промпт из истории
                full_context = ""
                for m in messages:
                    full_context += f"{m['role']}: {m['content']}\n"
                
                payload = {
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": full_context}]
                }
                
                resp = await client.post(url_chat, headers=chat_headers, json=payload)
                
                if resp.status_code == 200:
                    data = resp.text
                    # Ответ приходит стримом (SSE), собираем текст
                    text_parts = []
                    for line in data.split('\n'):
                        if 'data: ' in line:
                            try:
                                json_part = json.loads(line.replace('data: ', ''))
                                if 'message' in json_part:
                                    text_parts.append(json_part['message'])
                            except: pass
                    return "".join(text_parts)
                    
        except Exception as e:
            logger.error(f"DDG Error: {e}")
        return ""

    @staticmethod
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        system_prompt = get_system_prompt(mode)
        
        messages = [{"role": "system", "content": system_prompt}]
        for msg in history: messages.append(msg)
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        # ЗАПРОС
        response_text = await ChatManager.ask_duckduckgo(messages)

        # РЕЗЕРВ
        if not response_text:
            backups = [
                "Связь с космосом прервана... 🛸",
                "Мои нейроны отдыхают, лови вайб! 🎧",
                "Что-то не слышу, повтори?",
                "Аврора на связи! (Перезагрузка)"
            ]
            response_text = random.choice(backups)
        else:
            response_text = ChatManager.clean_response(response_text)

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text