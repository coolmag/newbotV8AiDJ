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

# === БЕСПЛАТНЫЕ ПРОВАЙДЕРЫ ===
# Puter требует API ключ - активируем только если есть ключ в окружении
PUTER_CONFIG = AIProviderConfig(
    "Puter", 
    os.getenv("PUTER_API_KEY", ""), 
    "https://api.puter.com/v1/chat/completions", 
    "gpt-4o", 
    bool(os.getenv("PUTER_API_KEY"))
)

# HuggingFace - ОТКЛЮЧЕН (старый API несовместим, требует нового формата)
# HF_CONFIG = AIProviderConfig(
#     "HuggingFace", 
#     os.getenv("HF_TOKEN", ""), 
#     "https://api-inference.huggingface.co/models/meta-llama/Llama-3-8B-Instruct",
#     "meta-llama/Llama-3-8B-Instruct", 
#     bool(os.getenv("HF_TOKEN"))
# )

# OpenRouter - бесплатные модели (могут быть перегружены, но работают)
OPENROUTER_MISTRAL_FREE = AIProviderConfig(
    "OpenRouterMistral", 
    os.getenv("OPENROUTER_API_KEY", ""), 
    "https://openrouter.ai/api/v1/chat/completions", 
    "mistralai/mistral-7b-instruct:free", 
    bool(os.getenv("OPENROUTER_API_KEY"))
)

# Более стабильная модель
OPENROUTER_QWEN_FREE = AIProviderConfig(
    "OpenRouterQwen", 
    os.getenv("OPENROUTER_API_KEY", ""), 
    "https://openrouter.ai/api/v1/chat/completions", 
    "qwen/qwen-2.5-7b-instruct:free", 
    bool(os.getenv("OPENROUTER_API_KEY"))
)

OPENROUTER_LLAMA_FREE = AIProviderConfig(
    "OpenRouterLlama", 
    os.getenv("OPENROUTER_API_KEY", ""), 
    "https://openrouter.ai/api/v1/chat/completions", 
    "meta-llama/llama-3.2-3b-instruct:free", 
    bool(os.getenv("OPENROUTER_API_KEY"))
)

# Nexra - бесплатный провайдер
NEXRA_CONFIG = AIProviderConfig(
    "Nexra", 
    "", 
    "https://api.nexra.ai/chat/completions", 
    "openhermes", 
    True  # Всегда активен, бесплатен
)

# === ПРОВАЙДЕРЫ С КЛЮЧАМИ ===
GIGACHAT_CONFIG = AIProviderConfig("GigaChat", os.getenv("GIGACHAT_CREDENTIALS", ""), "https://gigachat.devices.sberbank.ru/api/v1", "GigaChat", bool(os.getenv("GIGACHAT_CREDENTIALS")))
GROQ_CONFIG = AIProviderConfig("Groq", os.getenv("GROQ_API_KEY", ""), "https://api.groq.com/openai/v1/chat/completions", "llama-3.1-8b-instruct", bool(os.getenv("GROQ_API_KEY")))
DEEPSEEK_CONFIG = AIProviderConfig("DeepSeek", os.getenv("DEEPSEEK_API_KEY", ""), "https://api.deepseek.com/chat/completions", "deepseek-chat", bool(os.getenv("DEEPSEEK_API_KEY")))
NOVITA_CONFIG = AIProviderConfig("Novita", os.getenv("NOVITA_API_KEY", ""), "https://api.novita.ai/v3/openai/chat/completions", "meta-llama/llama-3.3-70b-instruct", bool(os.getenv("NOVITA_API_KEY")))
TOGETHER_CONFIG = AIProviderConfig("Together", os.getenv("TOGETHER_API_KEY", ""), "https://api.together.xyz/v1/chat/completions", "meta-llama/Llama-3-8b-chat-hf", bool(os.getenv("TOGETHER_API_KEY")))
PERPLEXITY_CONFIG = AIProviderConfig("Perplexity", os.getenv("PERPLEXITY_API_KEY", ""), "https://api.perplexity.ai/chat/completions", "llama-3.1-sonar-small-128k-online", bool(os.getenv("PERPLEXITY_API_KEY")))
COHERE_CONFIG = AIProviderConfig("Cohere", os.getenv("COHERE_API_KEY", ""), "https://api.cohere.ai/v1/chat", "command-r-plus", bool(os.getenv("COHERE_API_KEY")))
ANTHROPIC_CONFIG = AIProviderConfig("Anthropic", os.getenv("ANTHROPIC_API_KEY", ""), "https://api.anthropic.com/v1/messages", "claude-3-haiku-20240307", bool(os.getenv("ANTHROPIC_API_KEY")))
KODACODE_CONFIG = AIProviderConfig("KodaCode", os.getenv("KODACODE_API_KEY", ""), os.getenv("KODACODE_BASE_URL", "https://kodacode.ru/v1"), os.getenv("KODACODE_MODEL", "gpt-4o"), bool(os.getenv("KODACODE_API_KEY")))

GEMINI_KEYS = _parse_gemini_keys()
GEMINI_CONFIGS = []  # Gemini используется через gemini_init.py

def get_active_providers() -> List[AIProviderConfig]:
    providers, seen = [], set()
    # Бесплатные провайдеры (без ключа или с ключом)
    for cfg in [OPENROUTER_MISTRAL_FREE, OPENROUTER_QWEN_FREE, OPENROUTER_LLAMA_FREE, NEXRA_CONFIG]:
        if cfg.name not in seen and cfg.is_active:
            providers.append(cfg); seen.add(cfg.name)
            logger.info(f"[AI Config] {cfg.name} is ACTIVE (free)")
    
    # Провайдеры с ключами (если настроены)
    for cfg in [GROQ_CONFIG, DEEPSEEK_CONFIG, NOVITA_CONFIG, TOGETHER_CONFIG, KODACODE_CONFIG]:
        if cfg.name not in seen and cfg.is_active:
            providers.append(cfg); seen.add(cfg.name)
            logger.info(f"[AI Config] {cfg.name} is ACTIVE")
    
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