import os
import logging
from dataclasses import dataclass
from typing import List
from pathlib import Path

logger = logging.getLogger(__name__)

def _get_debug_log_path():
    """Get path to debug log file, works on both Windows and Linux"""
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
    # Для ротации ключей
    key_index: int = 0  # Индекс ключа в списке (для Gemini)

def _parse_gemini_keys() -> List[str]:
    """Парсит несколько Gemini ключей из переменной окружения (через запятую)"""
    keys_env = os.getenv("GEMINI_API_KEYS", "")
    if not keys_env:
        # Попробовать одиночный ключ
        single_key = os.getenv("GEMINI_API_KEY", "")
        return [single_key] if single_key else []
    # Разделить по запятой и очистить
    return [k.strip() for k in keys_env.split(",") if k.strip()]

def _get_kodacode_models() -> List[str]:
    """Получает доступные модели от KodaCode"""
    models_env = os.getenv("KODACODE_MODELS", "gpt-4o,claude-sonnet-4-20250514,gemini-2.5-pro")
    return [m.strip() for m in models_env.split(",") if m.strip()]

# === KODACODE (OpenAI-совместимый) ===
# ВНИМАНИЕ: KodaCode временно недоступен (404). Отключен.
KODACODE_CONFIG = AIProviderConfig(
    name="KodaCode",
    api_key=os.getenv("KODACODE_API_KEY", "sk-0"),
    base_url=os.getenv("KODACODE_BASE_URL", "https://api.kodacode.ru/v1"),
    model=os.getenv("KODACODE_MODEL", "gpt-4o"),
    is_active=False,  # Отключен - сервис недоступен
    key_index=0
)

# === GEMINI С РОТАЦИЕЙ КЛЮЧЕЙ ===
# Примечание: Gemini используется через gemini_init.py (Google GenAI SDK)
# Здесь только для совместимости с интерфейсом
GEMINI_KEYS = _parse_gemini_keys()
GEMINI_CONFIGS = []

for i, key in enumerate(GEMINI_KEYS):
    config = AIProviderConfig(
        name=f"Gemini_{i+1}",
        api_key=key,
        base_url="",  # Не используется - Gemini работает через SDK
        model="",
        is_active=bool(key),
        key_index=i
    )
    GEMINI_CONFIGS.append(config)

# Если нет ключей, добавляем пустой для обработки
if not GEMINI_CONFIGS:
    GEMINI_CONFIGS.append(AIProviderConfig(
        name="Gemini_1",
        api_key=os.getenv("GEMINI_API_KEY", ""),
        base_url="https://generativelanguage.googleapis.com/v1beta",
        model="gemini-2.5-flash",
        is_active=False,
        key_index=0
    ))

# === OPENROUTER БЕСПЛАТНЫЕ МОДЕЛИ ===
OPENROUTER_FREE_MODELS = [
    ("openrouter_free_mistral", "mistralai/mistral-7b-instruct:free"),
    ("openrouter_free_llama", "meta-llama/llama-3.2-3b-instruct:free"),
    ("openrouter_free_qwen", "qwen/qwen-2.5-72b-instruct:free"),
]

# 1. GIGACHAT (Сбер) — СТАВИМ ПЕРВЫМ!
# Самый надежный вариант для РФ.
GIGACHAT_CONFIG = AIProviderConfig(
    name="GigaChat",
    api_key=os.getenv("GIGACHAT_CREDENTIALS", ""),
    base_url="https://gigachat.devices.sberbank.ru/api/v1",
    model="GigaChat",
    is_active=bool(os.getenv("GIGACHAT_CREDENTIALS"))
)

# 2. HUGGING FACE — Новый API router
HF_CONFIG = AIProviderConfig(
    name="HuggingFace",
    api_key=os.getenv("HF_TOKEN", ""),
    base_url="https://router.huggingface.co/huggingface",
    model="meta-llama/Llama-3-8b-instruct",
    is_active=bool(os.getenv("HF_TOKEN"))
)

# 3. OPENROUTER (Mistral Free)
# Gemini Free глючит, пробуем Mistral
OPENROUTER_CONFIG = AIProviderConfig(
    name="OpenRouter",
    api_key=os.getenv("OPENROUTER_API_KEY", ""),
    base_url="https://openrouter.ai/api/v1/chat/completions",
    model="mistralai/mistral-7b-instruct:free",
    is_active=bool(os.getenv("OPENROUTER_API_KEY"))
)

# GROQ — Быстрый резерв
GROQ_CONFIG = AIProviderConfig(
    name="Groq",
    api_key=os.getenv("GROQ_API_KEY", ""),
    base_url="https://api.groq.com/openai/v1/chat/completions",
    model="llama-3.1-8b-instruct",
    is_active=bool(os.getenv("GROQ_API_KEY"))
)
NOVITA_CONFIG = AIProviderConfig("Novita", os.getenv("NOVITA_API_KEY", ""), "https://api.novita.ai/v3/openai/chat/completions", "meta-llama/llama-3.3-70b-instruct", bool(os.getenv("NOVITA_API_KEY")))
DEEPSEEK_CONFIG = AIProviderConfig("DeepSeek", os.getenv("DEEPSEEK_API_KEY", ""), "https://api.deepseek.com/chat/completions", "deepseek-chat", bool(os.getenv("DEEPSEEK_API_KEY")))

# Бесплатные провайдеры
TOGETHER_CONFIG = AIProviderConfig("Together", os.getenv("TOGETHER_API_KEY", ""), "https://api.together.xyz/v1/chat/completions", "meta-llama/Llama-3-8b-chat-hf", bool(os.getenv("TOGETHER_API_KEY")))
PERPLEXITY_CONFIG = AIProviderConfig("Perplexity", os.getenv("PERPLEXITY_API_KEY", ""), "https://api.perplexity.ai/chat/completions", "llama-3.1-sonar-small-128k-online", bool(os.getenv("PERPLEXITY_API_KEY")))
COHERE_CONFIG = AIProviderConfig("Cohere", os.getenv("COHERE_API_KEY", ""), "https://api.cohere.ai/v1/chat", "command-r-plus", bool(os.getenv("COHERE_API_KEY")))
ANTHROPIC_CONFIG = AIProviderConfig("Anthropic", os.getenv("ANTHROPIC_API_KEY", ""), "https://api.anthropic.com/v1/messages", "claude-3-haiku-20240307", bool(os.getenv("ANTHROPIC_API_KEY")))
# OpenRouter с разными бесплатными моделями
OPENROUTER_MISTRAL_FREE = AIProviderConfig("OpenRouterMistral", os.getenv("OPENROUTER_API_KEY", ""), "https://openrouter.ai/api/v1/chat/completions", "mistralai/mistral-7b-instruct:free", bool(os.getenv("OPENROUTER_API_KEY")))
OPENROUTER_LLAMA_FREE = AIProviderConfig("OpenRouterLlama", os.getenv("OPENROUTER_API_KEY", ""), "https://openrouter.ai/api/v1/chat/completions", "meta-llama/llama-3.2-3b-instruct:free", bool(os.getenv("OPENROUTER_API_KEY")))

# === NEW FREE PROVIDERS ===
VENUSAI_CONFIG = AIProviderConfig(
    name="VenusAI",
    api_key=os.getenv("VENUSAI_API_KEY", ""),
    base_url="https://api.venusai.com/v1",
    model="meta-llama/Llama-3.2-3B-Instruct",
    is_active=bool(os.getenv("VENUSAI_API_KEY"))
)

INTELLAPI_CONFIG = AIProviderConfig(
    name="IntelliAPI",
    api_key=os.getenv("INTELLAPI_API_KEY", ""),
    base_url="https://api.intellapi.com/v1",
    model="meta-llama/Llama-3.2-3B-Instruct",
    is_active=bool(os.getenv("INTELLAPI_API_KEY"))
)

def get_active_providers() -> List[AIProviderConfig]:
    import logging
    logger = logging.getLogger(__name__)
    
    providers = []
    seen = set()  # Для удаления дубликатов
    
    # === ПРИОРИТЕТ 1: GIGACHAT (Сбер) ===
    if GIGACHAT_CONFIG.is_active and "GigaChat" not in seen:
        providers.append(GIGACHAT_CONFIG)
        seen.add("GigaChat")
        logger.info(f"[AI Config] GigaChat is ACTIVE")
    else:
        logger.warning(f"[AI Config] GigaChat is INACTIVE")
    
    # === ПРИОРИТЕТ 2: Groq (если есть ключ) ===
    if GROQ_CONFIG.is_active and "Groq" not in seen:
        providers.append(GROQ_CONFIG)
        seen.add("Groq")
        logger.info(f"[AI Config] Groq is ACTIVE")
    
    # === ПРИОРИТЕТ 3: OpenRouter бесплатные ===
    if OPENROUTER_MISTRAL_FREE.is_active and "OpenRouterMistral" not in seen:
        providers.append(OPENROUTER_MISTRAL_FREE)
        seen.add("OpenRouterMistral")
        logger.info(f"[AI Config] OpenRouter Mistral Free is ACTIVE")
    if OPENROUTER_LLAMA_FREE.is_active and "OpenRouterLlama" not in seen:
        providers.append(OPENROUTER_LLAMA_FREE)
        seen.add("OpenRouterLlama")
        logger.info(f"[AI Config] OpenRouter Llama Free is ACTIVE")
    
    # === ПРИОРИТЕТ 4: HuggingFace ===
    if HF_CONFIG.is_active and "HuggingFace" not in seen:
        providers.append(HF_CONFIG)
        seen.add("HuggingFace")
        logger.info(f"[AI Config] HuggingFace is ACTIVE")
    
    # === ПРИОРИТЕТ 5: VenusAI (free) ===
    if VENUSAI_CONFIG.is_active and "VenusAI" not in seen:
        providers.append(VENUSAI_CONFIG)
        seen.add("VenusAI")
        logger.info(f"[AI Config] VenusAI is ACTIVE (free)")
    else:
        logger.warning(f"[AI Config] VenusAI is INACTIVE")
    
    # === ПРИОРИТЕТ 6: IntelliAPI (free) ===
    if INTELLAPI_CONFIG.is_active and "IntelliAPI" not in seen:
        providers.append(INTELLAPI_CONFIG)
        seen.add("IntelliAPI")
        logger.info(f"[AI Config] IntelliAPI is ACTIVE (free)")
    else:
        logger.warning(f"[AI Config] IntelliAPI is INACTIVE")
    
    # === РЕЗЕРВЫ ===
    if TOGETHER_CONFIG.is_active and "Together" not in seen:
        providers.append(TOGETHER_CONFIG); seen.add("Together")
    if PERPLEXITY_CONFIG.is_active and "Perplexity" not in seen:
        providers.append(PERPLEXITY_CONFIG); seen.add("Perplexity")
    if COHERE_CONFIG.is_active and "Cohere" not in seen:
        providers.append(COHERE_CONFIG); seen.add("Cohere")
    if ANTHROPIC_CONFIG.is_active and "Anthropic" not in seen:
        providers.append(ANTHROPIC_CONFIG); seen.add("Anthropic")
    if OPENROUTER_CONFIG.is_active and "OpenRouter" not in seen:
        providers.append(OPENROUTER_CONFIG); seen.add("OpenRouter")
    if NOVITA_CONFIG.is_active and "Novita" not in seen:
        providers.append(NOVITA_CONFIG); seen.add("Novita")
    if DEEPSEEK_CONFIG.is_active and "DeepSeek" not in seen:
        providers.append(DEEPSEEK_CONFIG); seen.add("DeepSeek")
    
    logger.info(f"[AI Config] Total active providers: {len(providers)}")
    if providers:
        for p in providers:
            logger.info(f"[AI Config]   - {p.name} ({p.model})")
    else:
        logger.warning("[AI Config] NO ACTIVE PROVIDERS! Only Gemini fallback will work.")
    
    return providers


def get_gemini_client_for_key(key_index: int = 0):
    """Получает Gemini клиент для определенного ключа"""
    if key_index < len(GEMINI_KEYS) and GEMINI_KEYS[key_index]:
        try:
            from google import genai
            return genai.Client(api_key=GEMINI_KEYS[key_index])
        except Exception as e:
            logger.error(f"[Gemini] Failed to create client for key {key_index}: {e}")
            return None
    return None
git config user.email "tyca77@gmail.com"
git config user.name "Coolmag"
cd "C:\Users\tyca7\Desktop\newbotV8AiD\newbotV8AiDJ-main"
git status
git add ai_config.py
git status
git commit -m "Add free AI providers: VenusAI, IntelliAPI"
git push
git log --oneline -3
git add ai_config.py
git commit -m "Fix ai_config.py - clean file"
git push