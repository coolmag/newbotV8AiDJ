import logging
import os
import random
import re
from collections import deque, defaultdict
import asyncio

# OFFICIAL HUGGING FACE CLIENT
try:
    from huggingface_hub import AsyncInferenceClient
    HAS_HF = True
except ImportError:
    HAS_HF = False

logger = logging.getLogger(__name__)

chat_histories = defaultdict(lambda: deque(maxlen=6))
chat_modes = defaultdict(lambda: "default")

PERSONAS = {
    "default": "Ты DJ Aurora. Веселая, дерзкая. Отвечай кратко, используй эмодзи.",
    "toxic": "Ты DJ Aurora. Саркастичная и злая. Не любишь глупые вопросы.",
    "gop": "Ты Аврора с района. Дерзкая, на ты, сленг.",
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
        junk = ["Hugging Face", "Assistant", "AI model", "OpenAI", "ChatGPT", "<|im_end|>", "<|im_start|>"]
        for phrase in junk:
            text = re.sub(f"(?i){phrase}", "Aurora", text)
        return text.strip()

    # --- HUGGING FACE INFERENCE ---
    @staticmethod
    async def ask_huggingface(messages: list) -> str:
        token = os.getenv("HF_TOKEN")
        if not token or not HAS_HF: 
            return "" # Нет ключа - молчим (или фолбэк)

        # Qwen 2.5 72B - Топовая модель, доступная бесплатно
        model = "Qwen/Qwen2.5-72B-Instruct"
        
        try:
            client = AsyncInferenceClient(token=token)
            
            # Формируем промпт в формате ChatML (Qwen это любит)
            prompt = ""
            for m in messages:
                role = m["role"]
                content = m["content"]
                prompt += f"<|im_start|>{role}\n{content}<|im_end|>\n"
            prompt += "<|im_start|>assistant\n"

            response = await client.text_generation(
                prompt, 
                model=model, 
                max_new_tokens=150, 
                temperature=0.7,
                stop_sequences=["<|im_end|>"]
            )
            return response
        except Exception as e:
            logger.error(f"HF Error: {e}")
        return ""

    @staticmethod
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        
        system_instruction = get_system_prompt(mode)
        
        messages = [{"role": "system", "content": system_instruction}]
        for msg in history:
            messages.append(msg)
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        # ЗАПРОС К HUGGING FACE
        response_text = await ChatManager.ask_huggingface(messages)

        # FALLBACK (Если ключа нет или лимит)
        if not response_text:
            backups = [
                "Связь с космосом прервана... 🛸",
                "Мои нейроны отдыхают, лови вайб! 🎧",
                "Аврора на связи! (Перезагрузка)"
            ]
            response_text = random.choice(backups)
        else:
            response_text = ChatManager.clean_response(response_text)

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text