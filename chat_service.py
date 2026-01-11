import logging
import os
import random
import re
from collections import deque, defaultdict
import asyncio

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
    "default": ["Связь с космосом барахлит...", "Мои нейроны отдыхают.", "Что-то интернет лагает, повтори?"],
    "toxic": ["Отвали, я занята.", "Ты скучный."],
    "gop": ["Слыш, связь плохая.", "Че сказал?"],
    "chill": ["Вайб прерван...", "Космос молчит..."]
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
        # Удаляем ссылки
        text = re.sub(r'http[s]?://\S+', '', text)
        # Удаляем мусор
        junk = [
            "GigaChat", "Сбер", "AI language model", "OpenAI", 
            "Want best roleplay", "llmplayground", "created by"
        ]
        for phrase in junk:
            # Удаляем фразу и всё что после неё, если это похоже на подпись
            if "roleplay" in phrase or "llm" in phrase:
                 text = re.sub(f"(?i){phrase}.*", "", text)
            else:
                 text = re.sub(f"(?i){phrase}", "Aurora", text)
        return text.strip()

    @staticmethod
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        
        system_instruction = get_system_prompt(mode)
        
        messages = [{"role": "system", "content": system_instruction}]
        for msg in history: messages.append(msg)
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        response_text = ""
        
        # 1. GIGACHAT (PRIORITY)
        giga_key = os.getenv("GIGACHAT_CREDENTIALS")
        if HAS_GIGACHAT and giga_key:
            try:
                def ask_sber():
                    # Отключаем проверку SSL, так как в контейнерах часто нет корневых сертификатов МинЦифры
                    with GigaChat(credentials=giga_key, scope="GIGACHAT_API_PERS", verify_ssl_certs=False) as giga:
                        return giga.chat(messages).choices[0].message.content
                
                response_text = await asyncio.get_running_loop().run_in_executor(None, ask_sber)
            except Exception as e:
                logger.error(f"GigaChat Error: {e}")

        # 2. G4F (BACKUP)
        if not response_text:
            try:
                def ask_g4f():
                    client = G4FClient()
                    return client.chat.completions.create(
                        model=g4f.models.gpt_4o_mini,
                        messages=messages
                    ).choices[0].message.content
                
                response_text = await asyncio.get_running_loop().run_in_executor(None, ask_g4f)
            except Exception as e:
                logger.warning(f"G4F Error: {e}")

        # 3. FALLBACK
        if not response_text:
            answers = OFFLINE_ANSWERS.get(mode, OFFLINE_ANSWERS["default"])
            response_text = random.choice(answers)
        else:
            response_text = ChatManager.clean_response(response_text)

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text