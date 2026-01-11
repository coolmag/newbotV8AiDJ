import logging
import re
from collections import deque, defaultdict
import asyncio
import g4f
from g4f.client import Client as G4FClient
from ai_personas import get_system_prompt, PERSONAS

logger = logging.getLogger(__name__)

chat_histories = defaultdict(lambda: deque(maxlen=10))
chat_modes = defaultdict(lambda: "default")

class ChatManager:
    @staticmethod
    def set_mode(chat_id: int, mode: str) -> bool:
        if mode in PERSONAS:
            chat_modes[chat_id] = mode
            chat_histories[chat_id].clear()
            return True
        return False

    @staticmethod
    def get_current_mode(chat_id: int) -> str:
        return chat_modes[chat_id]

    @staticmethod
    def clean_response(text: str) -> str:
        """Удаляет рекламу, ссылки и системный мусор."""
        if not text: return ""
        
        # 1. Удаляем ссылки (http/https/www)
        text = re.sub(r'http[s]?://\S+', '', text)
        text = re.sub(r'www\.\S+', '', text)
        
        # 2. Удаляем рекламные фразы провайдеров
        junk_phrases = [
            "Want best roleplay", "llmplayground", "created by", "OpenAI", 
            "ChatGPT", "AI language model", "language model"
        ]
        for phrase in junk_phrases:
            text = re.sub(f"(?i){phrase}.*", "", text) # Удаляем фразу и всё после нее
            
        # 3. Чистим лишние пробелы
        return text.strip()

    @staticmethod
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        
        system_instruction = get_system_prompt(mode)
        # Добавляем инструкцию "без цензуры и ссылок"
        system_instruction += " Отвечай коротко (1-2 фразы). Не присылай ссылки. Не говори, что ты ИИ."
        
        messages = [{"role": "system", "content": system_instruction}]
        for msg in history: messages.append(msg)
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        models_to_try = [
            "gpt-4o-mini",
            "gpt-4o", 
            "blackbox",
            g4f.models.default
        ]

        def ask_g4f():
            client = G4FClient()
            for model in models_to_try:
                try:
                    response = client.chat.completions.create(
                        model=model,
                        messages=messages
                    )
                    if response.choices and response.choices[0].message.content:
                        return response.choices[0].message.content
                except: continue
            return None

        response_text = None
        try:
            response_text = await asyncio.get_running_loop().run_in_executor(None, ask_g4f)
        except: pass

        if response_text:
            # ОЧИСТКА ОТ РЕКЛАМЫ
            response_text = ChatManager.clean_response(response_text)

        if not response_text:
            fallbacks = {
                "toxic": "Отвали, у меня пинг.",
                "gop": "Слыш, связь плохая.",
                "chill": "Космос молчит...",
                "default": "Что-то помехи. Повтори?"
            }
            return fallbacks.get(mode, "...")

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text