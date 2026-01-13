import os
import logging
import time
from pathlib import Path
from google import genai
from google.genai import errors

def _get_debug_log_path():
    """Get path to debug log file, works on both Windows and Linux"""
    base_dir = Path(__file__).resolve().parent
    log_path = base_dir / ".cursor" / "debug.log"
    return str(log_path)

logger = logging.getLogger("gemini")
HAS_GENAI = False
client = None
# Актуальные модели Gemini (обновлено 2025)
# Будем получать список доступных моделей динамически
MODELS = []  # Будет заполнен динамически

try:
    if k := os.getenv("GEMINI_API_KEY"):
        # #region agent log
        try:
            import json
            with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"gemini_init.py:12","message":"Gemini init: API key found","data":{"has_key":True,"key_length":len(k)},"timestamp":int(__import__("time").time()*1000)})+"\n")
        except: pass
        # #endregion
        client = genai.Client(api_key=k)
        HAS_GENAI = True
        # #region agent log
        try:
            import json
            with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"gemini_init.py:14","message":"Gemini init: client created","data":{"has_genai":HAS_GENAI,"client_exists":client is not None},"timestamp":int(__import__("time").time()*1000)})+"\n")
        except: pass
        # #endregion
    else:
        # #region agent log
        try:
            import json
            with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"gemini_init.py:12","message":"Gemini init: NO API key","data":{"has_key":False},"timestamp":int(__import__("time").time()*1000)})+"\n")
        except: pass
        # #endregion
except Exception as e:
    logger.error(f"[Gemini] Init exception: {e}", exc_info=True)
    # #region agent log
    try:
        import json
        with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"gemini_init.py:15","message":"Gemini init: exception","data":{"error":str(e)[:100]},"timestamp":int(__import__("time").time()*1000)})+"\n")
    except: 
        pass
    # #endregion
    pass

def generate_smart(prompt: str) -> str:
    logger.info(f"[Gemini] generate_smart called, HAS_GENAI={HAS_GENAI}, client_exists={client is not None}")
    if not HAS_GENAI or not client:
        return None

    # --- Упрощенная логика выбора модели ---
    best_model_name = None
    # Приоритетный список стабильных и бесплатных моделей
    PREFERRED_MODELS = [
        "gemini-1.5-flash", 
        "gemini-2.0-flash", 
        "gemini-flash-latest" 
    ]

    try:
        available_models = {m.name.replace('models/', ''): m for m in client.models.list()}
        
        for preferred in PREFERRED_MODELS:
            if preferred in available_models:
                best_model_name = preferred
                logger.info(f"[Gemini] Selected best model: {best_model_name}")
                break
        
        if not best_model_name:
            # Если ни одна из предпочитаемых моделей не найдена, попробуем найти любую flash модель
            for name in available_models.keys():
                if 'flash' in name and 'embedding' not in name and 'gecko' not in name:
                    best_model_name = name
                    logger.info(f"[Gemini] Found fallback flash model: {best_model_name}")
                    break

        if not best_model_name:
            logger.error("[Gemini] No suitable flash models found!")
            return None
            
    except Exception as e:
        logger.error(f"[Gemini] Could not list or select models: {e}", exc_info=True)
        return None

    # --- Упрощенная логика запроса ---
    try:
        logger.info(f"[Gemini] Trying model: {best_model_name}")
        response = client.models.generate_content(model=best_model_name, contents=prompt)
        
        result = None
        if hasattr(response, 'text') and response.text:
            result = response.text.strip()
        elif hasattr(response, 'candidates') and response.candidates:
            part = response.candidates[0].content.parts[0]
            if hasattr(part, 'text'):
                result = part.text.strip()

        if result:
            logger.info(f"[Gemini] Model {best_model_name} succeeded, result length: {len(result)}")
            return result
        else:
            logger.warning(f"[Gemini] Could not extract valid text from response.")
            return None
            
    except errors.ClientError as e:
        error_str = str(e)
        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower():
            # **Ключевое изменение:** Немедленный выход при лимите, без повторов и ожиданий.
            logger.warning(f"[Gemini] Rate limit (429) for model {best_model_name}. Failing fast.")
            return None
        else:
            logger.error(f"[Gemini] ClientError for {best_model_name}: {e}")
            return None
            
    except Exception as e:
        logger.error(f"[Gemini] Model {best_model_name} failed: {e}", exc_info=True)
        return None