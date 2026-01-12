import os
from dataclasses import dataclass
from typing import List
from pathlib import Path

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

# 1. GIGACHAT (Сбер) — СТАВИМ ПЕРВЫМ!
# Самый надежный вариант для РФ.
GIGACHAT_CONFIG = AIProviderConfig(
    name="GigaChat",
    api_key=os.getenv("GIGACHAT_CREDENTIALS", ""),
    base_url="https://gigachat.devices.sberbank.ru/api/v1",
    model="GigaChat",
    is_active=bool(os.getenv("GIGACHAT_CREDENTIALS"))
)

# 2. HUGGING FACE (НОВЫЙ URL ROUTER)
# Мы используем модель Qwen 2.5 (очень умная) через новый адрес роутера.
HF_CONFIG = AIProviderConfig(
    name="HuggingFace",
    api_key=os.getenv("HF_TOKEN", ""),
    # ВНИМАНИЕ: Новый формат URL для OpenAI-совместимости
    base_url="https://router.huggingface.co/hf-inference/models/Qwen/Qwen2.5-72B-Instruct/v1/chat/completions",
    model="Qwen/Qwen2.5-72B-Instruct",
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

# Остальные (Резерв)
GROQ_CONFIG = AIProviderConfig("Groq", os.getenv("GROQ_API_KEY", ""), "https://api.groq.com/openai/v1/chat/completions", "llama-3.3-70b-versatile", bool(os.getenv("GROQ_API_KEY")))
NOVITA_CONFIG = AIProviderConfig("Novita", os.getenv("NOVITA_API_KEY", ""), "https://api.novita.ai/v3/openai/chat/completions", "meta-llama/llama-3.3-70b-instruct", bool(os.getenv("NOVITA_API_KEY")))
DEEPSEEK_CONFIG = AIProviderConfig("DeepSeek", os.getenv("DEEPSEEK_API_KEY", ""), "https://api.deepseek.com/chat/completions", "deepseek-chat", bool(os.getenv("DEEPSEEK_API_KEY")))

def get_active_providers() -> List[AIProviderConfig]:
    providers = []
    # ЖЕСТКИЙ ПРИОРИТЕТ:
    # 1. Сбер (GigaChat)
    if GIGACHAT_CONFIG.is_active: providers.append(GIGACHAT_CONFIG)
    # 2. HuggingFace (Новый роутер)
    if HF_CONFIG.is_active: providers.append(HF_CONFIG)
    # 3. OpenRouter (Mistral)
    if OPENROUTER_CONFIG.is_active: providers.append(OPENROUTER_CONFIG)
    
    # Резервы
    if GROQ_CONFIG.is_active: providers.append(GROQ_CONFIG)
    if NOVITA_CONFIG.is_active: providers.append(NOVITA_CONFIG)
    if DEEPSEEK_CONFIG.is_active: providers.append(DEEPSEEK_CONFIG)
    
    # #region agent log
    try:
        import json
        with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"ai_config.py:49","message":"get_active_providers","data":{"count":len(providers),"active":[(p.name, p.is_active) for p in [GIGACHAT_CONFIG,HF_CONFIG,OPENROUTER_CONFIG,GROQ_CONFIG,NOVITA_CONFIG,DEEPSEEK_CONFIG]]},"timestamp":int(__import__("time").time()*1000)})+"\n")
    except: pass
    # #endregion
    
    return providers