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
MODELS = ['gemini-1.5-flash', 'gemini-1.5-flash-8b', 'gemini-2.0-flash-exp']

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
    # #region agent log
    try:
        import json
        with open(r"c:\Users\tyca7\Desktop\newbotV8AiD\newbotV8AiDJ-main\.cursor\debug.log", "a", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"gemini_init.py:15","message":"Gemini init: exception","data":{"error":str(e)[:100]},"timestamp":int(__import__("time").time()*1000)})+"\n")
    except: pass
    # #endregion
    pass

def generate_smart(prompt: str) -> str:
    # #region agent log
    try:
        import json
        with open(r"c:\Users\tyca7\Desktop\newbotV8AiD\newbotV8AiDJ-main\.cursor\debug.log", "a", encoding="utf-8") as f:
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
    for m in MODELS:
        try:
            response = client.models.generate_content(model=m, contents=prompt)
            # #region agent log
            try:
                import json
                with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"gemini_init.py:73","message":"generate_smart: got response object","data":{"model":m,"has_text_attr":hasattr(response,"text"),"response_type":type(response).__name__},"timestamp":int(__import__("time").time()*1000)})+"\n")
            except: pass
            # #endregion
            
            # Try to get text - it might be a property or method
            try:
                if hasattr(response, 'text'):
                    if callable(getattr(response, 'text', None)):
                        result = response.text()
                    else:
                        result = response.text
                elif hasattr(response, 'candidates') and response.candidates:
                    # Alternative: try to get text from candidates
                    if hasattr(response.candidates[0], 'content') and hasattr(response.candidates[0].content, 'parts'):
                        result = response.candidates[0].content.parts[0].text if response.candidates[0].content.parts else None
                    else:
                        result = None
                else:
                    result = None
            except Exception as e:
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
            
            # #region agent log
            try:
                import json
                with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"gemini_init.py:87","message":"generate_smart: success","data":{"model":m,"result_length":len(result) if result else 0,"result_preview":result[:50]},"timestamp":int(__import__("time").time()*1000)})+"\n")
            except: pass
            # #endregion
            return result
        except Exception as e:
            # #region agent log
            try:
                import json
                with open(_get_debug_log_path(), "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"gemini_init.py:90","message":"generate_smart: model failed","data":{"model":m,"error":str(e)[:100],"error_type":type(e).__name__},"timestamp":int(__import__("time").time()*1000)})+"\n")
            except: pass
            # #endregion
            time.sleep(1)
    # #region agent log
    try:
        import json
        with open(r"c:\Users\tyca7\Desktop\newbotV8AiD\newbotV8AiDJ-main\.cursor\debug.log", "a", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"gemini_init.py:23","message":"generate_smart: all models failed","data":{},"timestamp":int(__import__("time").time()*1000)})+"\n")
    except: pass
    # #endregion
    return None