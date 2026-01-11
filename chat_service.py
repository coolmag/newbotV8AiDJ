import logging
import os
import random
import re
from collections import deque, defaultdict
import asyncio

# HUGGING FACE
try:
    from huggingface_hub import AsyncInferenceClient
    HAS_HF = True
except ImportError:
    HAS_HF = False

# GIGACHAT
try:
    from gigachat import GigaChat
    HAS_GIGACHAT = True
except ImportError:
    HAS_GIGACHAT = False

from ai_personas import get_system_prompt, PERSONAS

logger = logging.getLogger(__name__)

chat_histories = defaultdict(lambda: deque(maxlen=6))
chat_modes = defaultdict(lambda: "default")

OFFLINE_ANSWERS = {
    "default": ["Связь с космосом барахлит...", "Мои нейроны отдыхают.", "Аврора на связи! (Перезагрузка)"],
    "toxic": ["Отвали, я занята.", "Скучно."],
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
        text = re.sub(r'http[s]?://\S+', '', text)
        junk = ["Hugging Face", "Assistant", "AI model", "OpenAI", "ChatGPT", "<|im_end|>", "<|im_start|>"]
        for phrase in junk:
            text = re.sub(f"(?i){phrase}", "Aurora", text)
        return text.strip()

    # --- HUGGING FACE CHAT (CORRECT METHOD) ---
    @staticmethod
    async def ask_huggingface(messages: list) -> str:
        token = os.getenv("HF_TOKEN")
        if not token or not HAS_HF: return ""

        # Qwen 2.5 72B - Топовая модель
        model = "Qwen/Qwen2.5-72B-Instruct"
        
        try:
            client = AsyncInferenceClient(token=token)
            
            # Используем правильный метод chat_completion
            response = await client.chat_completion(
                messages=messages, 
                model=model, 
                max_tokens=150, 
                temperature=0.7
            )
            
            if response.choices and response.choices[0].message:
                return response.choices[0].message.content
                
        except Exception as e:
            logger.error(f"HF Error: {e}")
        return ""

    @staticmethod
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        system_instruction = get_system_prompt(mode)
        
        # Формируем сообщения для Chat API
        messages = [{"role": "system", "content": system_instruction}]
        for msg in history:
            messages.append(msg)
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        response_text = ""
        
        # 1. GIGACHAT
        if HAS_GIGACHAT and os.getenv("GIGACHAT_CREDENTIALS"):
            try:
                def ask_sber():
                    with GigaChat(credentials=os.getenv("GIGACHAT_CREDENTIALS"), verify_ssl_certs=False) as giga:
                        return giga.chat(messages).choices[0].message.content
                response_text = await asyncio.get_running_loop().run_in_executor(None, ask_sber)
            except: pass

        # 2. HUGGING FACE (Основной)
        if not response_text and HAS_HF:
            response_text = await ChatManager.ask_huggingface(messages)

        # 3. FALLBACK
        if not response_text:
            answers = OFFLINE_ANSWERS.get(mode, OFFLINE_ANSWERS["default"])
            response_text = random.choice(answers)
        else:
            response_text = ChatManager.clean_response(response_text)

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text