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

        # БЕЗОПАСНЫЙ СПИСОК МОДЕЛЕЙ (Строками, чтобы не было AttributeError)
        models_to_try = [
            "gpt-4o-mini",
            "gpt-4o", 
            "blackbox",
            "llama-3.1-70b",
            g4f.models.default # Самая стандартная модель
        ]

        def ask_g4f():
            client = G4FClient()
            for model in models_to_try:
                try:
                    # Пробуем получить ответ
                    response = client.chat.completions.create(
                        model=model,
                        messages=messages
                    )
                    # Проверяем, что ответ не пустой
                    if response.choices and response.choices[0].message.content:
                        return response.choices[0].message.content
                except Exception as e:
                    # Логируем, но не падаем
                    # print(f"Model {model} failed: {e}") 
                    continue
            return None

        response_text = None
        try:
            response_text = await asyncio.get_running_loop().run_in_executor(None, ask_g4f)
        except Exception as e:
            logger.error(f"Chat Loop Error: {e}")

        if not response_text:
            # Живые заглушки (Fallback)
            fallbacks = {
                "toxic": "Отвали, у меня пинг высокий.",
                "gop": "Слыш, связь плохая, перезвони.",
                "chill": "Космос сегодня молчит...",
                "quiz": "Я забыла вопрос. Давай следующий?",
                "default": "Что-то помехи в эфире. Повтори?"
            }
            return fallbacks.get(mode, "...")

        # Сохраняем в историю только если ответ был успешным
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text