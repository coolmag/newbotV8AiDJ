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
    "default": [
        "Связь с космосом барахлит... 🛸",
        "Мои нейроны отдыхают, лови вайб! 🎧",
        "Аврора на связи! (Перезагрузка ⚙️)",
        "Что-то интернет лагает, повтори?"
    ],
    "toxic": ["Отвали, я занята.", "Скучно.", "Не беси меня."],
    "gop": ["Слыш, связь плохая.", "Че сказал?", "Погодь, ща трек доиграет."],
    "chill": ["Вайб прерван... помехи...", "Космос молчит...", "Просто наслаждайся..."]
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

    # --- HUGGING FACE INFERENCE ---
    @staticmethod
    async def ask_huggingface(messages: list) -> str:
        token = os.getenv("HF_TOKEN")
        if not token or not HAS_HF: return ""

        model = "Qwen/Qwen2.5-72B-Instruct"
        
        try:
            # Увеличиваем таймаут до 25 сек (Qwen 72B большая)
            client = AsyncInferenceClient(token=token, timeout=25.0)
            
            response = await client.chat_completion(
                messages=messages, 
                model=model, 
                max_tokens=150, 
                temperature=0.8
            )
            
            content = ""
            if response.choices and response.choices[0].message:
                content = response.choices[0].message.content
            
            logger.info(f"HF Response len: {len(content)}")
            return content
                
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

        response_text = ""
        
        # 1. GIGACHAT (Если есть)
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

        # 3. FALLBACK (ГАРАНТИРОВАННЫЙ ОТВЕТ)
        if not response_text or len(response_text.strip()) < 2:
            answers = OFFLINE_ANSWERS.get(mode, OFFLINE_ANSWERS["default"])
            response_text = random.choice(answers)
        else:
            response_text = ChatManager.clean_response(response_text)

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text