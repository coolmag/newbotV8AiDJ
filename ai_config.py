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

# 1. GIGACHAT (Sber) - Самый надежный для РФ
GIGACHAT_CONFIG = AIProviderConfig(
    name="GigaChat",
    api_key=os.getenv("GIGACHAT_CREDENTIALS", ""),
    base_url="https://gigachat.devices.sberbank.ru/api/v1",
    model="GigaChat",
    is_active=bool(os.getenv("GIGACHAT_CREDENTIALS"))
)

# 2. HUGGING FACE (Исправленный URL)
HF_CONFIG = AIProviderConfig(
    name="HuggingFace",
    api_key=os.getenv("HF_TOKEN", ""),
    base_url="https://api-inference.huggingface.co/models/Qwen/Qwen2.5-72B-Instruct/v1/chat/completions",
    model="Qwen/Qwen2.5-72B-Instruct",
    is_active=bool(os.getenv("HF_TOKEN"))
)

# 3. OPENROUTER (Llama Free)
OPENROUTER_CONFIG = AIProviderConfig(
    name="OpenRouter",
    api_key=os.getenv("OPENROUTER_API_KEY", ""),
    base_url="https://openrouter.ai/api/v1/chat/completions",
    model="meta-llama/llama-3-8b-instruct:free",
    is_active=bool(os.getenv("OPENROUTER_API_KEY"))
)

# 4. NOVITA
NOVITA_CONFIG = AIProviderConfig(
    name="Novita",
    api_key=os.getenv("NOVITA_API_KEY", ""),
    base_url="https://api.novita.ai/v3/openai/chat/completions",
    model="meta-llama/llama-3.3-70b-instruct",
    is_active=bool(os.getenv("NOVITA_API_KEY"))
)

# 5. GROQ
GROQ_CONFIG = AIProviderConfig(
    name="Groq",
    api_key=os.getenv("GROQ_API_KEY", ""),
    base_url="https://api.groq.com/openai/v1/chat/completions",
    model="llama-3.3-70b-versatile",
    is_active=bool(os.getenv("GROQ_API_KEY"))
)

# 6. DEEPSEEK
DEEPSEEK_CONFIG = AIProviderConfig(
    name="DeepSeek",
    api_key=os.getenv("DEEPSEEK_API_KEY", ""),
    base_url="https://api.deepseek.com/chat/completions",
    model="deepseek-chat",
    is_active=bool(os.getenv("DEEPSEEK_API_KEY"))
)

def get_active_providers() -> List[AIProviderConfig]:
    providers = []
    # Порядок приоритета (от самого стабильного к остальным)
    if GIGACHAT_CONFIG.is_active: providers.append(GIGACHAT_CONFIG) # №1 GigaChat
    if HF_CONFIG.is_active: providers.append(HF_CONFIG)
    if OPENROUTER_CONFIG.is_active: providers.append(OPENROUTER_CONFIG)
    if NOVITA_CONFIG.is_active: providers.append(NOVITA_CONFIG)
    if GROQ_CONFIG.is_active: providers.append(GROQ_CONFIG)
    if DEEPSEEK_CONFIG.is_active: providers.append(DEEPSEEK_CONFIG)
    return providers