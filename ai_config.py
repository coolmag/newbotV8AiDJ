import os
from dataclasses import dataclass

@dataclass
class AIProviderConfig:
    api_key: str
    base_url: str
    model: str
    is_active: bool

# Настройки для Groq (Самый быстрый бесплатный тир)
# Получить ключ: https://console.groq.com/keys
GROQ_CONFIG = AIProviderConfig(
    api_key=os.getenv("GROQ_API_KEY", ""),
    base_url="https://api.groq.com/openai/v1",
    model="llama3-8b-8192",
    is_active=bool(os.getenv("GROQ_API_KEY"))
)

# Настройки для DeepSeek (Очень дешевый и умный)
# Получить ключ: https://platform.deepseek.com/
DEEPSEEK_CONFIG = AIProviderConfig(
    api_key=os.getenv("DEEPSEEK_API_KEY", ""),
    base_url="https://api.deepseek.com/v1",
    model="deepseek-chat",
    is_active=bool(os.getenv("DEEPSEEK_API_KEY"))
)

# Выбор активного конфига
def get_active_config():
    if GROQ_CONFIG.is_active: return GROQ_CONFIG
    if DEEPSEEK_CONFIG.is_active: return DEEPSEEK_CONFIG
    return None # Fallback to G4F
