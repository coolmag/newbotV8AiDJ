import os
import logging
from dataclasses import dataclass
from typing import List
from pathlib import Path

logger = logging.getLogger(__name__)

def _get_debug_log_path():
    base_dir = Path(__file__).resolve().parent
    log_path = base_dir / ".cursor" / "debug.log"
    return str(log_path)

@dataclass
class AIProviderConfig:
    name: str
    api_key: str
    base_url: str
    model: str
    is_active: bool

def _parse_gemini_keys() -> List[str]:
    keys_env = os.getenv("GEMINI_API_KEYS", "")
    if not keys_env:
        single_key = os.getenv("GEMINI_API_KEY", "")
        return [single_key] if single_key else []
    return [k.strip() for k in keys_env.split(",") if k.strip()]

# === АКТУАЛЬНЫЕ БЕСПЛАТНЫЕ ПРОВАЙДЕРЫ (без ключа) ===

# HuggingFace Inference API — БЕСПЛАТНО, 1000+ моделей
HF_CONFIG = AIProviderConfig(
    "HuggingFace",
    os.getenv("HF_TOKEN", ""),  # Токен опционально, но лучше иметь
    "https://api-inference.huggingface.co/models/",
    "microsoft/Phi-3-mini-4k-instruct",  # Быстрая модель
    bool(os.getenv("HF_TOKEN", ""))  # Активен если есть токен
)

# === ПРОВАЙДЕРЫ С БЕСПЛАТНЫМ TIER (нужен ключ, но есть free credits) ===

# Groq - Был бесплатным, но требует валидный ключ
# Проверить ключ на https://console.groq.com/keys
GROQ_CONFIG = AIProviderConfig(
    "Groq", 
    os.getenv("GROQ_API_KEY", ""), 
    "https://api.groq.com/openai/v1/chat/completions", 
    "llama-3.3-70b-versatile",  # Обновлённая модель 2025
    bool(os.getenv("GROQ_API_KEY"))
)

# DeepSeek - Не работает без баланса
DEEPSEEK_CONFIG = AIProviderConfig(
    "DeepSeek", 
    os.getenv("DEEPSEEK_API_KEY", ""), 
    "https://api.deepseek.com/chat/completions", 
    "deepseek-chat", 
    bool(os.getenv("DEEPSEEK_API_KEY"))
)

# OpenRouter — даёт бесплатные кредиты при регистрации
OPENROUTER_CONFIG = AIProviderConfig(
    "OpenRouter",
    os.getenv("OPENROUTER_API_KEY", ""),
    "https://openrouter.ai/api/v1",
    "anthropic/claude-3-haiku",  # Бесплатная модель
    bool(os.getenv("OPENROUTER_API_KEY"))
)

GEMINI_KEYS = _parse_gemini_keys()
GEMINI_CONFIGS = []  # Gemini используется через gemini_init.py

def get_active_providers() -> List[AIProviderConfig]:
    providers, seen = [], set()
    
    # === БЕСПЛАТНЫЕ ПРОВАЙДЕРЫ (без ключа или с опциональным) ===
    # HuggingFace Inference API — полностью бесплатный
    if HF_CONFIG.name not in seen and HF_CONFIG.is_active:
        providers.append(HF_CONFIG); seen.add(HF_CONFIG.name)
        logger.info(f"[AI Config] HuggingFace is ACTIVE (free tier)")
    
    # === Провайдеры с БЕСПЛАТНЫМ TIER (нужен ключ) ===
    for cfg in [GROQ_CONFIG, DEEPSEEK_CONFIG, OPENROUTER_CONFIG]:
        if cfg.name not in seen and cfg.is_active:
            providers.append(cfg); seen.add(cfg.name)
            logger.info(f"[AI Config] {cfg.name} is ACTIVE (free tier)")
    
    logger.info(f"[AI Config] Total active providers: {len(providers)}")
    return providers

def get_gemini_client_for_key(key_index: int = 0):
    if key_index < len(GEMINI_KEYS) and GEMINI_KEYS[key_index]:
        try:
            from google import genai
            return genai.Client(api_key=GEMINI_KEYS[key_index])
        except Exception as e:
            logger.error(f"[Gemini] Failed: {e}")
    return None

# === НЕИСПОЛЬЗУЕМЫЕ ПРОВАЙДЕРЫ (отключены) ===
# NEXRA_CONFIG - DNS error, домен не существует
# GIGACHAT_CONFIG - требует специфичную авторизацию
# TOGETHER_CONFIG - требует отдельный ключ
# PERPLEXITY_CONFIG - требует отдельный ключ  
# COHERE_CONFIG - требует отдельный ключ
# ANTHROPIC_CONFIG - требует отдельный ключ
# KODACODE_CONFIG - 404 ошибка, домен не существует
# NOVITA_CONFIG - 403 недостаточно баланса
# OPENROUTER_MISTRAL_FREE - выдавал мусор
# OPENROUTER_QWEN_FREE - выдавал мусор
# OPENROUTER_LLAMA_FREE - выдавал мусор