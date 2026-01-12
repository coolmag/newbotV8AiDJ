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

# 1. HUGGING FACE (Пробуем самую легкую модель, она всегда доступна)
HF_CONFIG = AIProviderConfig(
    name="HuggingFace",
    api_key=os.getenv("HF_TOKEN", ""),
    # Стандартный URL Inference API
    base_url="https://api-inference.huggingface.co/models/microsoft/Phi-3-mini-4k-instruct/v1/chat/completions",
    model="microsoft/Phi-3-mini-4k-instruct", # Очень легкая и быстрая
    is_active=bool(os.getenv("HF_TOKEN"))
)

# 2. OPENROUTER (Обновляем ID на актуальный Free)
OPENROUTER_CONFIG = AIProviderConfig(
    name="OpenRouter",
    api_key=os.getenv("OPENROUTER_API_KEY", ""),
    base_url="https://openrouter.ai/api/v1/chat/completions",
    # Эта модель сейчас точно бесплатна и активна
    model="google/gemini-2.0-flash-exp:free", 
    is_active=bool(os.getenv("OPENROUTER_API_KEY"))
)

# Остальные оставляем как есть
GIGACHAT_CONFIG = AIProviderConfig("GigaChat", os.getenv("GIGACHAT_CREDENTIALS", ""), "https://gigachat.devices.sberbank.ru/api/v1", "GigaChat", bool(os.getenv("GIGACHAT_CREDENTIALS")))
GROQ_CONFIG = AIProviderConfig("Groq", os.getenv("GROQ_API_KEY", ""), "https://api.groq.com/openai/v1/chat/completions", "llama-3.3-70b-versatile", bool(os.getenv("GROQ_API_KEY")))
NOVITA_CONFIG = AIProviderConfig("Novita", os.getenv("NOVITA_API_KEY", ""), "https://api.novita.ai/v3/openai/chat/completions", "meta-llama/llama-3.3-70b-instruct", bool(os.getenv("NOVITA_API_KEY")))
DEEPSEEK_CONFIG = AIProviderConfig("DeepSeek", os.getenv("DEEPSEEK_API_KEY", ""), "https://api.deepseek.com/chat/completions", "deepseek-chat", bool(os.getenv("DEEPSEEK_API_KEY")))

def get_active_providers() -> List[AIProviderConfig]:
    providers = []
    # Новый приоритет: OpenRouter (Gemini Free) -> HF (Phi-3) -> GigaChat
    if OPENROUTER_CONFIG.is_active: providers.append(OPENROUTER_CONFIG)
    if HF_CONFIG.is_active: providers.append(HF_CONFIG)
    if GIGACHAT_CONFIG.is_active: providers.append(GIGACHAT_CONFIG)
    
    if GROQ_CONFIG.is_active: providers.append(GROQ_CONFIG)
    if NOVITA_CONFIG.is_active: providers.append(NOVITA_CONFIG)
    if DEEPSEEK_CONFIG.is_active: providers.append(DEEPSEEK_CONFIG)
    return providers
