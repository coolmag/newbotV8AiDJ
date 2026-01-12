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

# 1. HUGGING FACE (Исправленный URL!)
# Теперь используем router.huggingface.co
HF_CONFIG = AIProviderConfig(
    name="HuggingFace",
    api_key=os.getenv("HF_TOKEN", ""),
    # Новый формат URL
    base_url="https://router.huggingface.co/hf-inference/v1/chat/completions", 
    # Стабильная и быстрая модель
    model="meta-llama/Meta-Llama-3-8B-Instruct",
    is_active=bool(os.getenv("HF_TOKEN"))
)

# 2. OPENROUTER (Уходим от Google к Llama)
OPENROUTER_CONFIG = AIProviderConfig(
    name="OpenRouter",
    api_key=os.getenv("OPENROUTER_API_KEY", ""),
    base_url="https://openrouter.ai/api/v1/chat/completions",
    # Используем бесплатную Llama, так как Gemini блочит IP
    model="meta-llama/llama-3-8b-instruct:free",
    is_active=bool(os.getenv("OPENROUTER_API_KEY"))
)

# 3. GROQ (Оставляем как резерв)
GROQ_CONFIG = AIProviderConfig(
    name="Groq",
    api_key=os.getenv("GROQ_API_KEY", ""),
    base_url="https://api.groq.com/openai/v1/chat/completions",
    model="llama-3.3-70b-versatile",
    is_active=bool(os.getenv("GROQ_API_KEY"))
)

# 4. NOVITA (Оставляем как резерв)
NOVITA_CONFIG = AIProviderConfig(
    name="Novita",
    api_key=os.getenv("NOVITA_API_KEY", ""),
    base_url="https://api.novita.ai/v3/openai/chat/completions",
    model="meta-llama/llama-3.3-70b-instruct", 
    is_active=bool(os.getenv("NOVITA_API_KEY"))
)

# 5. DEEPSEEK
DEEPSEEK_CONFIG = AIProviderConfig(
    name="DeepSeek",
    api_key=os.getenv("DEEPSEEK_API_KEY", ""),
    base_url="https://api.deepseek.com/chat/completions",
    model="deepseek-chat",
    is_active=bool(os.getenv("DEEPSEEK_API_KEY"))
)

def get_active_providers() -> List[AIProviderConfig]:
    """Приоритет изменен: Сначала HF и OpenRouter (Llama)"""
    providers = []
    
    # Сначала пробуем HF (он надежный и вы его починили)
    if HF_CONFIG.is_active: providers.append(HF_CONFIG)
    
    # Потом OpenRouter (бесплатная Llama)
    if OPENROUTER_CONFIG.is_active: providers.append(OPENROUTER_CONFIG)
    
    # Потом остальные
    if GROQ_CONFIG.is_active: providers.append(GROQ_CONFIG)
    if NOVITA_CONFIG.is_active: providers.append(NOVITA_CONFIG)
    if DEEPSEEK_CONFIG.is_active: providers.append(DEEPSEEK_CONFIG)
    
    return providers
