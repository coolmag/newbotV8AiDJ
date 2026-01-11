import logging
from collections import deque, defaultdict
import g4f
from ai_personas import get_system_prompt, PERSONAS

logger = logging.getLogger(__name__)

# Память
chat_histories = defaultdict(lambda: deque(maxlen=10))
chat_modes = defaultdict(lambda: "default")

# ОБНОВЛЕННЫЙ СПИСОК ПРОВАЙДЕРОВ (Стабильные на 2026)
PROVIDERS = [
    g4f.Provider.Liaobots,
    g4f.Provider.Blackbox,
    g4f.Provider.GeekGpt,
    g4f.Provider.FreeGpt
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
    def get_current_mode(chat_id: int) -> str:
        return chat_modes[chat_id]

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
        
        # Перебор провайдеров с логированием
        for provider in PROVIDERS:
            try:
                response = await g4f.ChatCompletion.create_async(
                    model=g4f.models.gpt_35_turbo,
                    messages=messages,
                    provider=provider,
                    timeout=20
                )
                if response:
                    response_text = str(response)
                    break
            except Exception as e:
                logger.warning(f"Provider {provider.__name__} failed: {e}")
                continue
            
        if not response_text:
            # Резервные фразы, если ИИ совсем умер
            fallbacks = {
                "toxic": "Отвали, у меня сервер лагает.",
                "chill": "Звезды сегодня не сошлись...",
                "gop": "Слыш, связь плохая.",
                "default": "Что-то я тебя не слышу. Повтори?"
            }
            return fallbacks.get(mode, "Система перегружена.")

        # Сохраняем в историю
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text