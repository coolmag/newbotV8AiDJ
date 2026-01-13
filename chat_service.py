import logging
import random
import uuid
import httpx
import asyncio
import json
import os
import re
from pathlib import Path
from collections import deque, defaultdict
from typing import Optional, Dict, List

from ai_config import get_active_providers, AIProviderConfig, KODACODE_CONFIG
from ai_personas import get_system_prompt
from gemini_init import generate_smart, HAS_GENAI

def _get_debug_log_path():
    """Get path to debug log file, works on both Windows and Linux"""
    base_dir = Path(__file__).resolve().parent
    log_path = base_dir / ".cursor" / "debug.log"
    return str(log_path)

logger = logging.getLogger(__name__)

chat_histories = defaultdict(lambda: deque(maxlen=10))
chat_modes = defaultdict(lambda: "default")

# === QUIZ STATE MANAGEMENT ===
# Хранит состояние викторины для каждого чата
quiz_state = {}  # {chat_id: {"asked": set(), "last_question": str, "question_num": int}}

# База вопросов викторины
QUIZ_QUESTIONS = [
    {"q": "Какой инструмент играет соло в песне 'Smoke on the Water' группы Deep Purple?", "a": ["гитара", "электрогитара"]},
    {"q": "Какой жанр музыки ассоциируется с группой 'The Beatles'?", "a": ["рок", "рок-н-ролл"]},
    {"q": "Какой инструмент играет основную мелодию в песне 'Bohemian Rhapsody' группы Queen?", "a": ["пианино", "фортепиано"]},
    {"q": "Какой певец известен как 'Король поп-музыки'?", "a": ["майкл джексон", "michael jackson"]},
    {"q": "Какой музыкальный инструмент ассоциируется с Джими Хендриксом?", "a": ["электрогитара", "гитара"]},
    {"q": "Какой инструмент играет соло в песне 'Stairway to Heaven' группы 'Led Zeppelin'?", "a": ["электрогитара", "гитара"]},
    {"q": "Какой жанр музыки ассоциируется с группой 'Queen'?", "a": ["рок"]},
    {"q": "Какой инструмент играет соло в песне 'Comfortably Numb' группы 'Pink Floyd'?", "a": ["электрогитара", "гитара"]},
    {"q": "Какой музыкальный инструмент называют 'королём оркестра'?", "a": ["скрипка"]},
    {"q": "Какой жанр музыки ассоциируется с электронными битами и ритмами?", "a": ["электроника", "техно", "электронная"]},
    {"q": "Какой певец был участником группы 'The Beatles'?", "a": ["джон леннон", "пол маккартни", "джордж харрисон", "ринго старр"]},
    {"q": "Какой инструмент является основным в джазовой музыке?", "a": ["саксофон", "пианино"]},
    {"q": "Какой жанр музыки возник в США в начале 20 века?", "a": ["джаз", "блюз"]},
    {"q": "Какой русский композитор написал 'Щелкунчик'?", "a": ["чайковский"]},
    {"q": "Какой музыкальный инструмент используется в камерной музыке?", "a": ["скрипка", "виолончель", "альт"]},
]

# Команды выхода из режима викторины
QUIZ_EXIT_COMMANDS = [
    "выйти", "выход", "хватит", "стоп", "стоп_викторину", "стоп викторину",
    "enough", "stop", "exit", "quit", "выйди", "выйдем", "давай радио", 
    "включи радио", "хочу музыку", "давай музыку", "переключи", "смени режим",
    "ясно", "было уже", "не знаю"
]

class QuizManager:
    """Управление викториной"""
    
    @staticmethod
    def is_waiting_answer(chat_id: int) -> bool:
        """Проверяет, ожидаем ли мы ответа на вопрос"""
        state = quiz_state.get(chat_id)
        return state is not None and "question" in state and state["question"] is not None
    
    @staticmethod
    def check_answer(chat_id: int, user_answer: str) -> Optional[str]:
        """Проверяет ответ, возвращает реакцию или None если не в режиме викторины"""
        state = quiz_state.get(chat_id)
        if not state or "question" not in state or not state["question"]:
            return None
        
        user_answer_lower = user_answer.lower().strip()
        
        # Проверяем команды выхода
        for cmd in QUIZ_EXIT_COMMANDS:
            if cmd in user_answer_lower:
                QuizManager.stop(chat_id)
                return "🏁 Викторина завершена! Если хочешь — /admin для смены режима."
        
        # Проверяем ответ
        correct_answers = state.get("correct_answers", [])
        is_correct = any(correct in user_answer_lower for correct in correct_answers)
        
        if is_correct:
            result = "✅ Правильно! 🎉"
        else:
            correct = correct_answers[0] if correct_answers else "неизвестно"
            result = f"❌ Неправильно! Правильный ответ: {correct}."
        
        # Задаём следующий вопрос
        next_q = QuizManager._next_question(chat_id)
        return f"{result}\n\n{next_q}"
    
    @staticmethod
    def _next_question(chat_id: int) -> str:
        """Возвращает следующий вопрос"""
        if chat_id not in quiz_state:
            quiz_state[chat_id] = {"asked": set(), "question": None, "correct_answers": None, "question_num": 0}
        
        state = quiz_state[chat_id]
        
        # Выбираем неиспользованный вопрос
        available = [i for i in range(len(QUIZ_QUESTIONS)) if i not in state["asked"]]
        
        if not available:
            # Все вопросы использованы - начинаем заново
            state["asked"] = set()
            available = list(range(len(QUIZ_QUESTIONS)))
        
        q_idx = random.choice(available)
        state["asked"].add(q_idx)
        state["question_num"] += 1
        
        question_data = QUIZ_QUESTIONS[q_idx]
        state["question"] = question_data["q"]
        state["correct_answers"] = question_data["a"]
        
        return f"🎯 Вопрос #{state['question_num']}: {question_data['q']} ❓"
    
    @staticmethod
    def start_quiz(chat_id: int) -> str:
        """Начинает викторину"""
        quiz_state[chat_id] = {"asked": set(), "question": None, "correct_answers": None, "question_num": 0}
        return QuizManager._next_question(chat_id)
    
    @staticmethod
    def stop(chat_id: int):
        """Останавливает викторину"""
        if chat_id in quiz_state:
            del quiz_state[chat_id]

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
    async def _call_huggingface(client: httpx.AsyncClient, provider: AIProviderConfig, messages: list) -> str:
        """HuggingFace Inference API - полностью бесплатный с БОЛЬШИМ выбором моделей"""
        try:
            # HF использует URL с моделью в конце
            url = f"{provider.base_url}{provider.model}"
            logger.info(f"[HuggingFace] Calling {url}")
            
            headers = {
                "Authorization": f"Bearer {provider.api_key}" if provider.api_key else "",
                "Content-Type": "application/json"
            }
            
            # HF ожидает особый формат
            user_text = messages[-1]["content"] if messages else ""
            payload = {
                "inputs": user_text,
                "parameters": {
                    "max_new_tokens": 150,
                    "temperature": 0.7,
                    "do_sample": True
                }
            }
            
            resp = await client.post(url, json=payload, headers=headers, timeout=20.0)
            
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"[HuggingFace] Response type: {type(data)}")
                
                # HF может вернуть строку напрямую или dict
                if isinstance(data, str):
                    result = data
                elif isinstance(data, list) and len(data) > 0:
                    result = data[0].get("generated_text", "") or str(data[0])
                elif isinstance(data, dict) and "generated_text" in data:
                    result = data["generated_text"]
                else:
                    result = str(data)
                
                # Убираем дублирование входного текста если есть
                if result.startswith(user_text):
                    result = result[len(user_text):].strip()
                
                if result:
                    logger.info(f"[HuggingFace] Success, result length: {len(result)}")
                    return result
            else:
                logger.warning(f"[HuggingFace] Status {resp.status_code}: {resp.text[:200]}")
                if resp.status_code == 429:
                    logger.warning(f"[HuggingFace] Rate limited, trying again later")
        except Exception as e:
            logger.error(f"[HuggingFace] Error: {e}")
        return None

    @staticmethod
    async def _call_kodacode(client: httpx.AsyncClient, provider: AIProviderConfig, messages: list) -> str:
        """KodaCode API - OpenAI compatible with free models"""
        try:
            logger.info(f"[KodaCode] Calling {provider.base_url} with model {provider.model}")
            
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
        mode = chat_modes[chat_id]
        
        # === ПРОВЕРКА РЕЖИМА ВИКТОРИНЫ ===
        if mode == "quiz" and QuizManager.is_waiting_answer(chat_id):
            quiz_result = QuizManager.check_answer(chat_id, user_text)
            if quiz_result:
                # Добавляем в историю для контекста
                chat_histories[chat_id].append({"role": "user", "content": user_text})
                chat_histories[chat_id].append({"role": "assistant", "content": quiz_result})
                return quiz_result
        
        # === ПРОВЕРКА ЗАПУСКА ВИКТОРИНЫ В РЕЖИМЕ QUIZ ===
        if mode == "quiz" and not QuizManager.is_waiting_answer(chat_id):
            # Первый вопрос викторины
            quiz_result = QuizManager.start_quiz(chat_id)
            chat_histories[chat_id].append({"role": "assistant", "content": quiz_result})
            return quiz_result
        
        history = chat_histories[chat_id]
        messages = [{"role": "system", "content": get_system_prompt(mode)}]
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
                
                # Пропускаем Gemini - он используется через gemini_init.py
                if "Gemini" in provider.name:
                    logger.info(f"[ChatManager] Skipping Gemini (uses SDK directly)")
                    continue
                
                res = None
                try:
                    if provider.name == "GigaChat":
                        res = await ChatManager._call_gigachat(http_client, provider, messages)
                    elif provider.name == "Anthropic":
                        res = await ChatManager._call_anthropic(http_client, provider, messages)
                    elif provider.name == "Cohere":
                        res = await ChatManager._call_cohere(http_client, provider, messages)
                    elif provider.name == "HuggingFace":
                        res = await ChatManager._call_huggingface(http_client, provider, messages)
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