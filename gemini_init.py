import os
import logging
import time
from pathlib import Path
from google import genai

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
    except: pass
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
        
        # Filter models that support generateContent
        for model in available_models:
            if hasattr(model, 'supported_generation_methods') and model.supported_generation_methods:
                if 'generateContent' in model.supported_generation_methods:
                    model_name = model.name.replace('models/', '') if model.name.startswith('models/') else model.name
                    MODELS_TO_TRY.append(model_name)
                    logger.info(f"[Gemini] Found model with generateContent: {model_name}")
        
        if not MODELS_TO_TRY:
            logger.warning(f"[Gemini] No models with generateContent found, trying all models")
            # Try all models that have a name
            for model in available_models:
                if hasattr(model, 'name') and model.name:
                    model_name = model.name.replace('models/', '') if model.name.startswith('models/') else model.name
                    if model_name not in MODELS_TO_TRY:
                        MODELS_TO_TRY.append(model_name)
                        if len(MODELS_TO_TRY) >= 5:  # Limit to 5 models
                            break
            
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
        try:
            logger.info(f"[Gemini] Trying model: {m}")
            response = client.models.generate_content(model=m, contents=prompt)
            # #region agent log
            try:
                import json
                with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"gemini_init.py:73","message":"generate_smart: got response object","data":{"model":m,"has_text_attr":hasattr(response,"text"),"response_type":type(response).__name__},"timestamp":int(__import__("time").time()*1000)})+"\n")
            except: pass
            # #endregion
            
            # Try to get text - multiple methods
            try:
                result = None
                # Method 1: Try direct .text property/method
                if hasattr(response, 'text'):
                    text_attr = getattr(response, 'text', None)
                    if callable(text_attr):
                        result = text_attr()
                    else:
                        result = text_attr
                    # Convert to string if needed
                    if result is not None:
                        result = str(result).strip()
                        logger.info(f"[Gemini] Got text via .text, length: {len(result) if result else 0}")
                
                # Method 2: Try candidates path
                if (not result or not result.strip()) and hasattr(response, 'candidates') and response.candidates:
                    logger.info(f"[Gemini] Trying candidates path, count: {len(response.candidates)}")
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
                
                # Method 3: Try response.text directly (new SDK format)
                if (not result or not result.strip()):
                    try:
                        # Try accessing text as attribute directly
                        if hasattr(response, 'text') and response.text:
                            result = str(response.text).strip()
                            logger.info(f"[Gemini] Got text via direct response.text, length: {len(result) if result else 0}")
                    except Exception as e:
                        logger.warning(f"[Gemini] Error in method 3: {e}")
                        result = None
                
                # Validate result - check if it looks like garbage
                if result and result.strip():
                    result = result.strip()
                    # Check if result looks like valid text (not garbage from str() conversion)
                    garbage_patterns = ['Recommendlibftorage', 'яatisf', '/smайс', 'ammable', '❄️ammable', 'яatisf/smайс']
                    has_garbage = any(pattern in result for pattern in garbage_patterns)
                    too_many_colons = result.count(':') > 5
                    too_short = len(result) < 3
                    too_many_slashes = result.count('/') > 3
                    # Check for suspicious character patterns (like mixed Cyrillic/Latin garbage)
                    suspicious_chars = result.count('йс') > 0 and result.count('ammable') > 0
                    # Check if result is mostly non-printable or weird characters
                    printable_ratio = sum(1 for c in result if c.isprintable() or c.isspace()) / len(result) if result else 0
                    
                    if too_short or too_many_colons or has_garbage or too_many_slashes or suspicious_chars or printable_ratio < 0.7:
                        logger.warning(f"[Gemini] Result looks like garbage, rejecting: {result[:100]}")
                        logger.warning(f"[Gemini] Validation details: too_short={too_short}, too_many_colons={too_many_colons}, has_garbage={has_garbage}, too_many_slashes={too_many_slashes}, suspicious_chars={suspicious_chars}, printable_ratio={printable_ratio:.2f}")
                        result = None
                    else:
                        logger.info(f"[Gemini] Result validated successfully, length: {len(result)}")
                
                if not result or not result.strip():
                    logger.warning(f"[Gemini] Could not extract valid text from response, type: {type(response)}")
                    result = None
                    
            except Exception as e:
                logger.error(f"[Gemini] Error getting text from response: {e}", exc_info=True)
                # #region agent log
                try:
                    import json
                    with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"gemini_init.py:88","message":"generate_smart: error getting text","data":{"model":m,"error":str(e)[:100]},"timestamp":int(__import__("time").time()*1000)})+"\n")
                except: pass
                # #endregion
                result = None
            
            if result is None:
                # #region agent log
                try:
                    import json
                    with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"gemini_init.py:95","message":"generate_smart: result is None","data":{"model":m},"timestamp":int(__import__("time").time()*1000)})+"\n")
                except: pass
                # #endregion
                time.sleep(1)
                continue
            if not result or not result.strip():
                # #region agent log
                try:
                    import json
                    with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"gemini_init.py:78","message":"generate_smart: result is empty","data":{"model":m,"result_length":len(result) if result else 0},"timestamp":int(__import__("time").time()*1000)})+"\n")
                except: pass
                # #endregion
                time.sleep(1)
                continue
            
            logger.info(f"[Gemini] Model {m} succeeded, result length: {len(result)}, preview: {result[:50]}")
            # #region agent log
            try:
                import json
                with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"gemini_init.py:87","message":"generate_smart: success","data":{"model":m,"result_length":len(result) if result else 0,"result_preview":result[:50]},"timestamp":int(__import__("time").time()*1000)})+"\n")
            except: pass
            # #endregion
            return result
        except Exception as e:
            logger.error(f"[Gemini] Model {m} failed: {e}", exc_info=True)
            # #region agent log
            try:
                import json
                with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"gemini_init.py:90","message":"generate_smart: model failed","data":{"model":m,"error":str(e)[:100],"error_type":type(e).__name__},"timestamp":int(__import__("time").time()*1000)})+"\n")
            except: pass
            # #endregion
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