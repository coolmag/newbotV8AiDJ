# Force reload by adding a comment
import logging
import httpx
import asyncio
import json
import os

from ai_config import get_active_providers, AIProviderConfig
from gemini_init import generate_smart, HAS_GENAI

logger = logging.getLogger(__name__)

class AIManager:
    """
    Централизованный класс для взаимодействия с различными AI провайдерами.
    Обрабатывает каскадный вызов провайдеров и фоллбэк на Gemini.
    """

    @staticmethod
    async def _call_openrouter(client: httpx.AsyncClient, provider: AIProviderConfig, messages: list) -> str:
        """OpenRouter API - OpenAI compatible с разными провайдерами"""
        try:
            logger.info(f"[OpenRouter] Calling {provider.base_url} with model {provider.model}")
            headers = {
                "Authorization": f"Bearer {provider.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://telegram-bot",
                "X-Title": "DJ-Aurora-Bot"
            }
            payload = {"model": provider.model, "messages": messages, "max_tokens": 150, "temperature": 0.7}
            resp = await client.post(provider.base_url, json=payload, headers=headers, timeout=15.0)
            
            if resp.status_code == 200:
                content_type = resp.headers.get("content-type", "")
                if "application/json" not in content_type:
                    logger.warning(f"[OpenRouter] Test failed, unexpected content-type: {content_type}, response: {resp.text[:200]}")
                    return None
                data = resp.json()
                if "choices" in data and data["choices"]:
                    return data["choices"][0]["message"].get("content", "")
                else:
                    logger.warning(f"[OpenRouter] Test failed, no choices in response: {resp.text[:200]}")
            else:
                logger.warning(f"[OpenRouter] Test failed, status {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"[OpenRouter] Error during test: {e}", exc_info=True)
        return None

    @staticmethod
    async def _call_cloudflare(client: httpx.AsyncClient, provider: AIProviderConfig, messages: list) -> str:
        """Cloudflare Workers AI API"""
        try:
            # Cloudflare требует account_id в URL
            account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
            if not account_id:
                logger.warning(f"[Cloudflare] No account_id configured")
                return None
            
            # Подставляем account_id в URL
            url = provider.base_url.format(account_id=account_id)
            
            logger.info(f"[Cloudflare] Calling {url} with model {provider.model}")
            
            headers = {
                "Authorization": f"Bearer {provider.api_key}",
                "Content-Type": "application/json"
            }
            
            # Cloudflare использует OpenAI-совместимый формат
            payload = {
                "model": provider.model,
                "messages": messages,
                "max_tokens": 200,
                "temperature": 0.7
            }
            
            resp = await client.post(url, json=payload, headers=headers, timeout=15.0)
            
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"[Cloudflare] Response status: {resp.status_code}, data keys: {data.keys() if isinstance(data, dict) else 'list'}")
                
                if isinstance(data, dict):
                    # Cloudflare возвращает результат в структуре "result"
                    if "result" in data and isinstance(data["result"], dict):
                        if "response" in data["result"]:
                            return data["result"]["response"]
                        elif "text" in data["result"]:
                            return data["result"]["text"]
                    elif "response" in data:
                        return data["response"]
                    elif "choices" in data and data["choices"]:
                        return data["choices"][0]["message"].get("content", "")
            else:
                logger.warning(f"[Cloudflare] Status {resp.status_code}: {resp.text[:200]}")
                
        except Exception as e:
            logger.error(f"[Cloudflare] Error: {e}", exc_info=True)
        return None

    @staticmethod
    async def _call_generic(client: httpx.AsyncClient, provider: AIProviderConfig, messages: list) -> str:
        """Generic OpenAI-compatible provider call"""
        try:
            logger.info(f"[{provider.name}] Calling {provider.base_url} with model {provider.model}")
            headers = {"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"}
            payload = {"model": provider.model, "messages": messages, "max_tokens": 150}
            resp = await client.post(provider.base_url, json=payload, headers=headers, timeout=10.0)

            if resp.status_code == 200:
                data = resp.json()
                if "choices" in data and data["choices"]:
                    return data["choices"][0]["message"].get("content", "")
                else:
                    logger.warning(f"[{provider.name}] Test failed, no choices in response: {resp.text[:200]}")
            else:
                logger.warning(f"[{provider.name}] Test failed, status {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"[{provider.name}] Error during test: {e}", exc_info=True)
        return None

    @staticmethod
    async def get_ai_response(prompt: str, system_prompt: str = None) -> str:
        """
        Получает ответ от AI, используя каскад провайдеров.
        Сначала пробует платные/бесплатные провайдеры, затем Gemini.
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # 1. Платные/бесплатные провайдеры
        async with httpx.AsyncClient(verify=False) as http_client:
            active_providers = get_active_providers()
            logger.info(f"[AIManager] Active providers: {[p.name for p in active_providers]}")
            
            for provider in active_providers:
                logger.info(f"[AIManager] Trying provider: {provider.name}")
                res = None
                try:
                    if provider.name == "OpenRouter":
                        res = await AIManager._call_openrouter(http_client, provider, messages)
                    elif provider.name == "Cloudflare":
                        res = await AIManager._call_cloudflare(http_client, provider, messages)
                    else: # Groq, Deepseek и другие OpenAI-совместимые
                        res = await AIManager._call_generic(http_client, provider, messages)
                except Exception as e:
                    logger.error(f"[AIManager] Exception calling {provider.name}: {e}")
                
                if res and res.strip():
                    logger.info(f"[AIManager] Provider {provider.name} succeeded.")
                    return res
                else:
                    logger.warning(f"[AIManager] Provider {provider.name} failed or returned empty, trying next...")

        # 2. Фоллбэк на Gemini
        if HAS_GENAI:
            logger.info("[AIManager] Trying Gemini fallback...")
            # Для Gemini лучше простой промпт, без 'system'
            gemini_prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(None, lambda: generate_smart(gemini_prompt))
            if res and res.strip():
                logger.info("[AIManager] Gemini fallback succeeded.")
                return res

        logger.warning("[AIManager] All AI providers failed.")
        return None

    @staticmethod
    async def test_provider(provider: AIProviderConfig) -> str:
        """
        Выполняет легковесную проверку работоспособности провайдера.
        Возвращает "✅ OK" в случае успеха или "❌ FAILED" при любой ошибке.
        """
        async with httpx.AsyncClient(verify=False) as http_client:
            test_messages = [{"role": "user", "content": "Hi"}] # Более универсальный тестовый запрос
            res = None
            try:
                # Используем ту же логику диспетчеризации, что и в get_ai_response
                if provider.name == "OpenRouter":
                    res = await AIManager._call_openrouter(http_client, provider, test_messages)
                elif provider.name == "Cloudflare":
                    res = await AIManager._call_cloudflare(http_client, provider, test_messages)
                else: # Generic OpenAI-совместимые
                    res = await AIManager._call_generic(http_client, provider, test_messages)

                                # _call-методы возвращают None при любой ошибке, что нам и нужно

                                if res and res.strip(): # Любой непустой ответ считается успешным

                                    return "✅ OK"

                                

                                # Если ответ не пришел или пуст, считаем проверку проваленной

                                return "❌ FAILED"
            except Exception as e:
                logger.error(f"[TestProvider] Unhandled exception for {provider.name}: {e}")
                return "❌ ERROR"
