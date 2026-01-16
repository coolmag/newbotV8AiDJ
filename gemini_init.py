import os
import logging
import random
import asyncio
from typing import Optional
from google import genai
from google.genai import errors

logger = logging.getLogger("gemini")

# === ЗАГРУЗКА КЛЮЧЕЙ ===
def _load_keys():
    # Читаем список ключей из переменной окружения
    keys_str = os.getenv("GEMINI_API_KEYS", "")
    # Разделяем по запятой и чистим от пробелов
    keys = [k.strip() for k in keys_str.split(",") if k.strip()]
    
    # Если списка нет, пробуем старую переменную с одним ключом
    if not keys:
        single = os.getenv("GEMINI_API_KEY", "")
        if single:
            keys.append(single.strip())
            
    return keys

KEYS = _load_keys()
HAS_GENAI = len(KEYS) > 0

if HAS_GENAI:
    logger.info(f"[Gemini] System active. Loaded {len(KEYS)} API keys. Rotation enabled.")
else:
    logger.warning("[Gemini] No API keys found. Gemini disabled.")

# === СТРАТЕГИЯ ВЫБОРА МОДЕЛИ ===
# Используем только проверенные модели с высокими лимитами (Tier 1).
# Избегаем Experimental моделей (у которых 20-50 запросов в день).
MODELS_PRIORITY = [
    "gemini-1.5-flash",  # Основная: Быстрая, 1500 req/day
    "gemini-2.0-flash",  # Резерв 1: Новее, но может быть нестабильна
    "gemini-1.5-pro"     # Резерв 2: Мощная, но медленная
]

# Кэш клиентов, чтобы не пересоздавать объекты
client_cache = {}

def get_client(api_key: str):
    if api_key not in client_cache:
        client_cache[api_key] = genai.Client(api_key=api_key)
    return client_cache[api_key]

def generate_smart(prompt: str) -> Optional[str]:
    """
    Генерирует ответ, перебирая ключи и модели до успеха.
    """
    if not HAS_GENAI:
        return None

    # 1. Перемешиваем ключи (балансировка нагрузки)
    current_keys = list(KEYS)
    random.shuffle(current_keys)

    for api_key in current_keys:
        client = get_client(api_key)
        # Маскируем ключ для логов (показываем только последние 4 символа)
        key_id = f"...{api_key[-4:]}" if len(api_key) > 4 else "???"
        
        # 2. Перебираем модели для текущего ключа
        for model_name in MODELS_PRIORITY:
            try:
                # logger.debug(f"[Gemini] Trying {key_id} with {model_name}")
                
                response = client.models.generate_content(
                    model=model_name, 
                    contents=prompt
                )
                
                result = None
                if hasattr(response, 'text') and response.text:
                    result = response.text.strip()
                
                if result:
                    # Успех! Возвращаем результат сразу.
                    return result
                    
            except errors.ClientError as e:
                error_str = str(e)
                
                # Сценарий 1: Лимит исчерпан (429).
                # Решение: Бросаем этот ключ, выходим из цикла моделей, берем СЛЕДУЮЩИЙ КЛЮЧ.
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    logger.warning(f"[Gemini] Rate Limit on key {key_id}. Switching key...")
                    break 
                
                # Сценарий 2: Модель не найдена (404).
                # Решение: Пробуем следующую МОДЕЛЬ на этом же ключе.
                if "404" in error_str or "Not Found" in error_str:
                    logger.warning(f"[Gemini] Model {model_name} unavailable on key {key_id}. Trying next model...")
                    continue
                
                # Сценарий 3: Другая ошибка API (например, фильтр безопасности).
                logger.error(f"[Gemini] API Error {key_id} / {model_name}: {e}")
                    break
                
            except Exception as e:
                logger.error(f"[Gemini] Critical error: {e}")
                break

    logger.error("[Gemini] Failed to generate response after trying all keys and models.")
    return None
