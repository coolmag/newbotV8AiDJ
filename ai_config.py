import os
from dataclasses import dataclass
from typing import List

@dataclass
class AIProviderConfig:
    name: str
    api_key: str
    base_url: str
    model: str
    is_active: bool

# 1. GROQ (Если ключ невалиден, будет пропущен)
GROQ_CONFIG = AIProviderConfig(
    name="Groq",
    api_key=os.getenv("GROQ_API_KEY", ""),
    base_url="https://api.groq.com/openai/v1/chat/completions",
    model="llama3-8b-8192",
    is_active=bool(os.getenv("GROQ_API_KEY"))
)

# 2. OPENROUTER (Обновленная модель!)
# Используем generic free model, которая чаще всего доступна
OPENROUTER_CONFIG = AIProviderConfig(
    name="OpenRouter",
    api_key=os.getenv("OPENROUTER_API_KEY", ""),
    base_url="https://openrouter.ai/api/v1/chat/completions",
    # Заменили на более стабильный ID. Также можно пробовать google/gemini-2.0-flash-exp:free
    model="google/gemini-2.0-flash-lite-preview-02-05:free", 
    is_active=bool(os.getenv("OPENROUTER_API_KEY"))
)

# Если предыдущая модель все же не работает, попробуйте эту (раскомментируйте одну):
# model="meta-llama/llama-3-8b-instruct:free"
# model="google/gemini-2.0-flash-exp:free"

# 3. DEEPSEEK
DEEPSEEK_CONFIG = AIProviderConfig(
    name="DeepSeek",
    api_key=os.getenv("DEEPSEEK_API_KEY", ""),
    base_url="https://api.deepseek.com/chat/completions",
    model="deepseek-chat",
    is_active=bool(os.getenv("DEEPSEEK_API_KEY"))
)

def get_active_providers() -> List[AIProviderConfig]:
    providers = []
    # Порядок приоритета:
    if GROQ_CONFIG.is_active: providers.append(GROQ_CONFIG)
    if OPENROUTER_CONFIG.is_active: 
        # Hotfix: обновляем модель на лету, если старая не работает
        OPENROUTER_CONFIG.model = "google/gemini-2.0-flash-exp:free" 
        providers.append(OPENROUTER_CONFIG)
    if DEEPSEEK_CONFIG.is_active: providers.append(DEEPSEEK_CONFIG)
    return providers