import logging
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
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        system_instruction = get_system_prompt(mode)
        
        messages = [{"role": "system", "content": system_instruction}]
        for msg in history: messages.append(msg)
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        response_text = ""

        # G4F POOL (Бесплатные и доступные)
        # Мы пробуем несколько моделей, так как провайдеры могут отваливаться
        models_to_try = [
            g4f.models.gpt_4o_mini, # Обычно самый быстрый
            g4f.models.llama_3_1_70b,
            g4f.models.blackbox,    # Надежный
        ]

        def ask_g4f():
            client = G4FClient()
            for model in models_to_try:
                try:
                    response = client.chat.completions.create(
                        model=model,
                        messages=messages
                    )
                    if response.choices[0].message.content:
                        return response.choices[0].message.content
                except: continue
            return None

        try:
            response_text = await asyncio.get_running_loop().run_in_executor(None, ask_g4f)
        except Exception as e:
            logger.error(f"Chat AI Error: {e}")

        if not response_text:
            # Саркастичные заглушки, если ИИ умер
            fallbacks = {
                "toxic": "Мой интеллект слишком высок для твоих вопросов.",
                "gop": "Слыш, сеть не ловит.",
                "default": "Что-то помехи в эфире... Повтори?"
            }
            return fallbacks.get(mode, "...")

        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text