import logging
from collections import deque, defaultdict
import g4f
from ai_personas import get_system_prompt, PERSONAS

logger = logging.getLogger(__name__)

# Память: словарь, где ключ = chat_id, значение = очередь из 10 последних сообщений
chat_histories = defaultdict(lambda: deque(maxlen=10))

# Текущий режим для каждого чата
chat_modes = defaultdict(lambda: "default")

PROVIDERS = [
    g4f.Provider.GeekGpt,
    g4f.Provider.Liaobots,
    g4f.Provider.Blackbox,
    g4f.Provider.Chatgpt4o
]

class ChatManager:
    @staticmethod
    def set_mode(chat_id: int, mode: str) -> bool:
        if mode in PERSONAS:
            chat_modes[chat_id] = mode
            # При смене режима лучше очистить историю, чтобы не путать бота
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
        
        # Формируем промпт
        system_instruction = get_system_prompt(mode)
        
        # Собираем контекст для нейросети
        messages = [{"role": "system", "content": system_instruction}]
        
        # Добавляем историю
        for msg in history:
            messages.append(msg)
            
        # Добавляем текущее сообщение
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})
        
        # Запрос к AI
        response_text = ""
        for provider in PROVIDERS:
            try:
                response = await g4f.ChatCompletion.create_async(
                    model=g4f.models.gpt_35_turbo,
                    messages=messages,
                    provider=provider,
                    timeout=15
                )
                if response:
                    response_text = str(response)
                    break
            except: continue
            
        if not response_text:
            return "..." # Если ИИ сдох, просто молчим или ставим многозначительное троеточие

        # Сохраняем в историю (чтобы бот помнил контекст следующего ответа)
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": response_text})
        
        return response_text