import logging
import random
import uuid
import httpx
import asyncio
import json
import os
from pathlib import Path
from collections import deque, defaultdict

from ai_config import get_active_providers, AIProviderConfig, KODACODE_CONFIG
from gemini_init import generate_smart, HAS_GENAI

def _get_debug_log_path():
    """Get path to debug log file, works on both Windows and Linux"""
    base_dir = Path(__file__).resolve().parent
    log_path = base_dir / ".cursor" / "debug.log"
    return str(log_path)

logger = logging.getLogger(__name__)

chat_histories = defaultdict(lambda: deque(maxlen=6))
chat_modes = defaultdict(lambda: "default")

PERSONAS = {
    "default": "Ты DJ Aurora. Веселая, используй эмодзи.",
    "toxic": "Ты DJ Aurora (Toxic). Хами.",
    "gop": "Ты Аврора с района.",
    "chill": "Ты Аврора (Chill).",
    "quiz": "Ты Ведущая Викторины."
}

class ChatManager:
    @staticmethod
    def set_mode(chat_id: int, mode: str): chat_modes[chat_id] = mode
    @staticmethod
    def get_mode(chat_id: int): return chat_modes[chat_id]

    @staticmethod
    async def _call_gigachat(client: httpx.AsyncClient, provider: AIProviderConfig, messages: list) -> str:
        logger.info(f"[GigaChat] Attempting to call GigaChat API")
        # #region agent log
        try:
            with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"chat_service.py:31","message":"_call_gigachat ENTRY","data":{"has_api_key":bool(provider.api_key)},"timestamp":int(asyncio.get_event_loop().time()*1000)})+"\n")
        except: pass
        # #endregion
        try:
            auth_headers = {
                "Authorization": f"Bearer {provider.api_key}" if not provider.api_key.startswith("Basic") else provider.api_key,
                "RqUID": str(uuid.uuid4()),
                "Content-Type": "application/x-www-form-urlencoded"
            }
            if " " not in auth_headers["Authorization"]:
                auth_headers["Authorization"] = f"Basic {provider.api_key}"

            token_resp = await client.post(
                "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
                data={"scope": "GIGACHAT_API_PERS"},
                headers=auth_headers,
                verify=False,
                timeout=5.0
            )
            if token_resp.status_code != 200: 
                logger.warning(f"[GigaChat] Auth Fail: {token_resp.status_code}") # Added logging
                # #region agent log
                try:
                    with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"chat_service.py:49","message":"GigaChat auth failed","data":{"status_code":token_resp.status_code},"timestamp":int(asyncio.get_event_loop().time()*1000)})+"\n")
                except: pass
                # #endregion
                return None
            access_token = token_resp.json()["access_token"]

            chat_resp = await client.post(
                f"{provider.base_url}/chat/completions",
                json={"model": provider.model, "messages": messages, "max_tokens": 150},
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                verify=False,
                timeout=8.0 # Changed timeout from 10.0 to 8.0
            )
            if chat_resp.status_code == 200: 
                return chat_resp.json()["choices"][0]["message"]["content"]
            else:
                logger.warning(f"[GigaChat] Chat Fail: {chat_resp.status_code}") # Added logging
                # #region agent log
                try:
                    with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"chat_service.py:63","message":"GigaChat chat failed","data":{"status_code":chat_resp.status_code},"timestamp":int(asyncio.get_event_loop().time()*1000)})+"\n")
                except: pass
                # #endregion
        except Exception as e: # Catch specific exception
            logger.error(f"[GigaChat] Error: {e}") # Changed to error
            # #region agent log
            try:
                with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"chat_service.py:65","message":"GigaChat exception","data":{"error":str(e)[:100]},"timestamp":int(asyncio.get_event_loop().time()*1000)})+"\n")
            except: pass
            # #endregion
        return None

    @staticmethod
    async def _call_anthropic(client: httpx.AsyncClient, provider: AIProviderConfig, messages: list) -> str:
        """Anthropic Claude API uses different format"""
        try:
            headers = {
                "x-api-key": provider.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            }
            # Convert messages format for Anthropic
            system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
            user_messages = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
            
            payload = {
                "model": provider.model,
                "max_tokens": 150,
                "messages": user_messages
            }
            if system_msg:
                payload["system"] = system_msg
            
            resp = await client.post(provider.base_url, json=payload, headers=headers, timeout=8.0)
            if resp.status_code == 200:
                data = resp.json()
                if "content" in data and len(data["content"]) > 0:
                    return data["content"][0].get("text", "")
            else:
                logger.warning(f"[{provider.name}] Status {resp.status_code}: {resp.text[:100]}")
        except Exception as e:
            logger.warning(f"[{provider.name}] Error: {e}")
        return None

    @staticmethod
    async def _call_cohere(client: httpx.AsyncClient, provider: AIProviderConfig, messages: list) -> str:
        """Cohere API uses different format"""
        try:
            headers = {
                "Authorization": f"Bearer {provider.api_key}",
                "Content-Type": "application/json"
            }
            # Convert to Cohere format
            chat_history = []
            for m in messages[:-1]:  # All except last
                if m["role"] == "user":
                    chat_history.append({"role": "USER", "message": m["content"]})
                elif m["role"] == "assistant":
                    chat_history.append({"role": "CHATBOT", "message": m["content"]})
            
            payload = {
                "model": provider.model,
                "message": messages[-1]["content"] if messages else "",
                "chat_history": chat_history,
                "max_tokens": 150
            }
            
            resp = await client.post(provider.base_url, json=payload, headers=headers, timeout=8.0)
            if resp.status_code == 200:
                data = resp.json()
                if "text" in data:
                    return data["text"]
            else:
                logger.warning(f"[{provider.name}] Status {resp.status_code}: {resp.text[:100]}")
        except Exception as e:
            logger.warning(f"[{provider.name}] Error: {e}")
        return None

    @staticmethod
    async def _call_kodacode(client: httpx.AsyncClient, provider: AIProviderConfig, messages: list) -> str:
        """KodaCode API - OpenAI compatible with free models"""
        try:
            logger.info(f"[KodaCode] Calling {provider.base_url} with model {provider.model}")
            
            # KodaCode использует стандартный OpenAI-совместимый формат
            headers = {
                "Authorization": f"Bearer {provider.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": provider.model,
                "messages": messages,
                "max_tokens": 200,
                "temperature": 0.7
            }
            
            resp = await client.post(f"{provider.base_url}/chat/completions", json=payload, headers=headers, timeout=15.0)
            
            if resp.status_code == 200:
                data = resp.json()
                if "choices" in data and len(data["choices"]) > 0:
                    result = data["choices"][0]["message"]["content"]
                    logger.info(f"[KodaCode] Success, result length: {len(result)}")
                    return result
            else:
                error_text = resp.text[:200]
                logger.warning(f"[KodaCode] Status {resp.status_code}: {error_text}")
                # Если 429 - это rate limit, вернем None чтобы попробовать следующий провайдер
                if resp.status_code == 429:
                    return None
        except Exception as e:
            logger.warning(f"[KodaCode] Error: {e}")
        return None

    @staticmethod
    async def _call_generic(client: httpx.AsyncClient, provider: AIProviderConfig, messages: list) -> str:
        # #region agent log
        try:
            with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"chat_service.py:69","message":"_call_generic ENTRY","data":{"provider":provider.name,"has_api_key":bool(provider.api_key),"base_url":provider.base_url},"timestamp":int(asyncio.get_event_loop().time()*1000)})+"\n")
        except: pass
        # #endregion
        try:
            headers = {"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"}
            payload = {"model": provider.model, "messages": messages, "max_tokens": 150}
            
            logger.info(f"[{provider.name}] Calling {provider.base_url} with model {provider.model}")
            resp = await client.post(provider.base_url, json=payload, headers=headers, timeout=10.0)
            
            logger.info(f"[{provider.name}] Response status: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"[{provider.name}] Response keys: {list(data.keys()) if isinstance(data, dict) else 'list'}")
                
                # Try different response formats
                if "choices" in data and len(data["choices"]) > 0:
                    result = data["choices"][0]["message"]["content"]
                    logger.info(f"[{provider.name}] Got result from choices, length: {len(result)}")
                    return result
                if isinstance(data, list) and len(data) > 0 and "generated_text" in data[0]:
                    result = data[0]["generated_text"]
                    logger.info(f"[{provider.name}] Got result from generated_text, length: {len(result)}")
                    return result
                if "text" in data:
                    result = data["text"]
                    logger.info(f"[{provider.name}] Got result from text, length: {len(result)}")
                    return result
                logger.warning(f"[{provider.name}] Unknown response format: {str(data)[:200]}")
            else:
                logger.warning(f"[{provider.name}] Status {resp.status_code}: {resp.text[:200]}") # Added logging
                # #region agent log
                try:
                    with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"chat_service.py:80","message":"Generic provider failed","data":{"provider":provider.name,"status_code":resp.status_code,"error":resp.text[:200]},"timestamp":int(asyncio.get_event_loop().time()*1000)})+"\n")
                except: pass
                # #endregion
        except Exception as e: # Catch specific exception
            logger.error(f"[{provider.name}] Error: {e}", exc_info=True) # Changed to error
            # #region agent log
            try:
                with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"chat_service.py:82","message":"Generic provider exception","data":{"provider":provider.name,"error":str(e)[:200]},"timestamp":int(asyncio.get_event_loop().time()*1000)})+"\n")
            except: pass
            # #endregion
        return None

    @staticmethod
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        # #region agent log
        try:
            with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"chat_service.py:86","message":"get_response ENTRY","data":{"chat_id":chat_id,"user_text":user_text[:50],"user_name":user_name},"timestamp":int(asyncio.get_event_loop().time()*1000)})+"\n")
        except: pass
        # #endregion
        
        mode = chat_modes[chat_id]
        history = chat_histories[chat_id]
        messages = [{"role": "system", "content": PERSONAS.get(mode, "")}]
        for msg in history: messages.append(msg)
        messages.append({"role": "user", "content": f"{user_name}: {user_text}"})

        # #region agent log
        try:
            providers = get_active_providers()
            with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"chat_service.py:95","message":"Active providers check","data":{"count":len(providers),"providers":[p.name for p in providers],"has_gemini":HAS_GENAI},"timestamp":int(asyncio.get_event_loop().time()*1000)})+"\n")
        except: pass
        # #endregion

        # 1. Providers
        async with httpx.AsyncClient(verify=False) as http_client:
            active_providers = get_active_providers()
            logger.info(f"[ChatManager] Active providers: {[p.name for p in active_providers]}")
            
            for provider in active_providers:
                logger.info(f"[ChatManager] Trying provider: {provider.name}")
                # #region agent log
                try:
                    with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"chat_service.py:98","message":"Trying provider","data":{"provider":provider.name},"timestamp":int(asyncio.get_event_loop().time()*1000)})+"\n")
                except: pass
                # #endregion
                
                res = None
                try:
                    if provider.name == "GigaChat":
                        res = await ChatManager._call_gigachat(http_client, provider, messages)
                    elif provider.name == "Anthropic":
                        res = await ChatManager._call_anthropic(http_client, provider, messages)
                    elif provider.name == "Cohere":
                        res = await ChatManager._call_cohere(http_client, provider, messages)
                    elif "KodaCode" in provider.name:
                        res = await ChatManager._call_kodacode(http_client, provider, messages)
                    else:
                        res = await ChatManager._call_generic(http_client, provider, messages)
                except Exception as e:
                    logger.error(f"[ChatManager] Exception calling {provider.name}: {e}")
                    res = None
                
                logger.info(f"[ChatManager] Provider {provider.name} result: has_result={bool(res)}, length={len(res) if res else 0}")
                if res:
                    logger.info(f"[ChatManager] Provider {provider.name} result preview: {res[:100]}")
                
                # #region agent log
                try:
                    with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"chat_service.py:102","message":"Provider result","data":{"provider":provider.name,"has_result":bool(res),"result_length":len(res) if res else 0},"timestamp":int(asyncio.get_event_loop().time()*1000)})+"\n")
                except: pass
                # #endregion
                
                if res and res.strip(): # Проверка на пустую строку
                    logger.info(f"[ChatManager] Provider {provider.name} succeeded, returning result")
                    history.append({"role": "user", "content": user_text})
                    history.append({"role": "assistant", "content": res})
                    # #region agent log
                    try:
                        with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"E","location":"chat_service.py:105","message":"get_response EXIT (provider success)","data":{"provider":provider.name,"response_preview":res[:50]},"timestamp":int(asyncio.get_event_loop().time()*1000)})+"\n")
                    except: pass
                    # #endregion
                    return res
                else:
                    logger.warning(f"[ChatManager] Provider {provider.name} failed or returned empty, trying next...")

        # 2. Native Gemini
        # #region agent log
        try:
            with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"chat_service.py:110","message":"Trying Gemini fallback","data":{"has_genai":HAS_GENAI},"timestamp":int(asyncio.get_event_loop().time()*1000)})+"\n")
        except: pass
        # #endregion
        
        full_prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
        logger.info(f"[ChatManager] Trying Gemini fallback, prompt length: {len(full_prompt)}")
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, lambda: generate_smart(full_prompt))
        
        logger.info(f"[ChatManager] Gemini returned: has_result={bool(res)}, is_none={res is None}, type={type(res).__name__}, length={len(res) if res else 0}")
        if res:
            logger.info(f"[ChatManager] Gemini result preview: {str(res)[:100]}")
            # Additional validation - check for garbage patterns
            garbage_patterns = ['Recommendlibftorage', 'яatisf', '/smайс', 'ammable', '❄️ammable', 'яatisf/smайс']
            if any(pattern in str(res) for pattern in garbage_patterns):
                logger.warning(f"[ChatManager] Gemini result contains garbage patterns, rejecting")
                res = None
        
        # #region agent log
        try:
            with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"chat_service.py:195","message":"Gemini result (before check)","data":{"has_result":bool(res),"is_none":res is None,"result_type":type(res).__name__,"result_length":len(res) if res else 0,"result_preview":str(res)[:100] if res else None},"timestamp":int(asyncio.get_event_loop().time()*1000)})+"\n")
        except: pass
        # #endregion
        
        if res and res.strip():
            # Final validation before using
            if len(res.strip()) >= 3 and not any(p in res for p in ['Recommendlibftorage', 'яatisf/smайс']):
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": res})
                logger.info(f"[ChatManager] Gemini result accepted, returning")
                # #region agent log
                try:
                    with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"E","location":"chat_service.py:114","message":"get_response EXIT (Gemini success)","data":{"response_preview":res[:50]},"timestamp":int(asyncio.get_event_loop().time()*1000)})+"\n")
                except: pass
                # #endregion
                return res
            else:
                logger.warning(f"[ChatManager] Gemini result failed final validation, rejecting")

        # 3. GARANTEED FALLBACK (Никогда не возвращаем None)
        # #region agent log
        try:
            with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"E","location":"chat_service.py:117","message":"get_response EXIT (fallback)","data":{"fallback_used":True},"timestamp":int(asyncio.get_event_loop().time()*1000)})+"\n")
        except: pass
        # #endregion
        return "Сигнал нестабилен, но я тебя слышу! 📡"