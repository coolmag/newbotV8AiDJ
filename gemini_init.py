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
    # #region agent log
    try:
        import json
        with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"gemini_init.py:17","message":"generate_smart ENTRY","data":{"has_genai":HAS_GENAI,"client_exists":client is not None},"timestamp":int(__import__("time").time()*1000)})+"\n")
    except: pass
    # #endregion
    if not HAS_GENAI or not client: 
        # #region agent log
        try:
            import json
            with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"gemini_init.py:18","message":"generate_smart: early return","data":{"has_genai":HAS_GENAI,"client_exists":client is not None},"timestamp":int(__import__("time").time()*1000)})+"\n")
        except: pass
        # #endregion
        return None
    
    # Try to get list of available models first
    MODELS_TO_TRY = []
    try:
        available_models = list(client.models.list())
        logger.info(f"[Gemini] Found {len(available_models)} total models")
        # Log first few model names for debugging
        if available_models:
            logger.info(f"[Gemini] First 5 models: {[m.name for m in available_models[:5]]}")
        
        # Filter for FREE models only (Flash tier)
        # Priority: gemini-1.5-flash > gemini-2.0-flash > gemini-2.5-flash (у 2.5 маленький free tier!)
        free_model_patterns = ['flash', '1.5-flash', '1.5-pro']
        
        for model in available_models:
            if not hasattr(model, 'name') or not model.name:
                continue
                
            model_name = model.name.replace('models/', '') if model.name.startswith('models/') else model.name
            
            # Skip embedding models
            if 'embedding' in model_name.lower() or 'gecko' in model_name.lower():
                continue
            
            # PRIORITY 1: Flash models (free tier)
            is_flash = any(pattern in model_name.lower() for pattern in free_model_patterns)
            
            # PRIORITY 2: Modern gemini-2.x models
            is_gemini_2 = model_name.startswith('gemini-2.')
            
            # Skip expensive preview models (computer-use, native-audio, etc.)
            is_expensive_preview = any(x in model_name.lower() for x in [
                'computer-use', 'native-audio', 'pro-image', 'robotics', '1.5-pro'
            ])
            
            if is_expensive_preview:
                logger.debug(f"[Gemini] Skipping expensive model: {model_name}")
                continue
            
            if is_flash or is_gemini_2:
                MODELS_TO_TRY.append(model_name)
                logger.info(f"[Gemini] Found model: {model_name} (flash={is_flash}, gemini2={is_gemini_2})")
        
        # Priority: gemini-1.5-flash (1500/day) > gemini-2.0-flash > gemini-1.0-flash
        # SKIP: gemini-2.5-flash (only 20/day free tier - too restrictive!)
        def sort_key(name):
            # Skip 2.5-flash models entirely - they have very low free tier limits
            if '2.5-flash' in name:
                return (999, name)  # Push to the end (will be skipped)
            # Priority 1: 1.5-flash models (best free tier: 1500/day)
            elif '1.5-flash' in name:
                return (0, name)
            # Priority 2: 2.0-flash models
            elif '2.0-flash' in name:
                return (1, name)
            # Priority 3: Other flash models
            elif 'flash' in name:
                return (2, name)
            else:
                return (3, name)
        
        # Filter out 2.5-flash models and sort
        MODELS_TO_TRY = sorted(MODELS_TO_TRY, key=sort_key)[:5]
        
        # Remove any 2.5-flash models that slipped through
        MODELS_TO_TRY = [m for m in MODELS_TO_TRY if '2.5-flash' not in m]
        
        if not MODELS_TO_TRY:
            logger.error("[Gemini] No suitable models found!")
            return None
            
            if not MODELS_TO_TRY:
                logger.error("[Gemini] No models found at all!")
                return None
    except Exception as e:
        logger.error(f"[Gemini] Could not list models: {e}", exc_info=True)
        # Don't use fallback - return None to let other providers try
        logger.warning("[Gemini] Disabling Gemini to allow other providers to work")
        return None
    
    if not MODELS_TO_TRY:
        logger.error("[Gemini] No models to try!")
        return None
    
    for m in MODELS_TO_TRY:
        retry_count = 0
        max_retries = 3
        
        while retry_count < max_retries:
            try:
                logger.info(f"[Gemini] Trying model: {m} (attempt {retry_count + 1}/{max_retries})")
                response = client.models.generate_content(model=m, contents=prompt)
                
                # ... existing code to extract result ...
                result = None
                # Method 1: Try direct .text property/method
                if hasattr(response, 'text'):
                    text_attr = getattr(response, 'text', None)
                    if callable(text_attr):
                        result = text_attr()
                    else:
                        result = text_attr
                    if result is not None:
                        result = str(result).strip()
                        logger.info(f"[Gemini] Got text via .text, length: {len(result) if result else 0}")
                
                # Method 2: Try candidates path
                if (not result or not result.strip()) and hasattr(response, 'candidates') and response.candidates:
                    try:
                        candidate = response.candidates[0]
                        if hasattr(candidate, 'content'):
                            content = candidate.content
                            if hasattr(content, 'parts') and content.parts:
                                part = content.parts[0]
                                if hasattr(part, 'text'):
                                    result = str(part.text).strip()
                                    logger.info(f"[Gemini] Got text from candidates.parts, length: {len(result) if result else 0}")
                    except Exception as e:
                        logger.warning(f"[Gemini] Error extracting from candidates: {e}")
                
                # Validate result
                if result and result.strip():
                    result = result.strip()
                    garbage_patterns = ['Recommendlibftorage', 'яatisf', '/smайс', 'ammable', '❄️ammable', 'яatisf/smайс']
                    has_garbage = any(pattern in result for pattern in garbage_patterns)
                    too_short = len(result) < 3
                    
                    if too_short or has_garbage:
                        logger.warning(f"[Gemini] Result looks like garbage, rejecting: {result[:100]}")
                        result = None
                    else:
                        logger.info(f"[Gemini] Result validated successfully, length: {len(result)}")
                
                if result and result.strip():
                    logger.info(f"[Gemini] Model {m} succeeded, result length: {len(result)}")
                    return result
                
                if result is None:
                    logger.warning(f"[Gemini] Could not extract valid text from response")
                    return None
                    
            except errors.ClientError as e:
                error_str = str(e)
                # Проверяем разные форматы 429 ошибки
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower():
                    # RESOURCE_EXHAUSTED - rate limit, wait and retry
                    wait_time = (2 ** retry_count) * 30  # 30s, 60s, 120s
                    logger.warning(f"[Gemini] Rate limit (429) for model {m}, waiting {wait_time}s...")
                    time.sleep(wait_time)
                    retry_count += 1
                    continue
                else:
                    logger.error(f"[Gemini] ClientError for {m}: {e}")
                    break
                    
            except Exception as e:
                logger.error(f"[Gemini] Model {m} failed: {e}", exc_info=True)
                break
        
        if retry_count >= max_retries:
            logger.warning(f"[Gemini] Model {m} exceeded retries, trying next model...")
        time.sleep(1)
    logger.warning(f"[Gemini] All models failed, returning None")
    # #region agent log
    try:
        import json
        with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"gemini_init.py:23","message":"generate_smart: all models failed","data":{},"timestamp":int(__import__("time").time()*1000)})+"\n")
    except: pass
    # #endregion
    return None