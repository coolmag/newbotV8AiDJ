import os
import logging
import time
from google import genai

logger = logging.getLogger("gemini")
HAS_GENAI = False
client = None
MODELS = ['gemini-1.5-flash', 'gemini-1.5-flash-8b', 'gemini-2.0-flash-exp']

try:
    if k := os.getenv("GEMINI_API_KEY"):
        # #region agent log
        try:
            import json
            with open(r"c:\Users\tyca7\Desktop\newbotV8AiD\newbotV8AiDJ-main\.cursor\debug.log", "a", encoding="utf-8") as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"gemini_init.py:12","message":"Gemini init: API key found","data":{"has_key":True,"key_length":len(k)},"timestamp":int(__import__("time").time()*1000)})+"\n")
        except: pass
        # #endregion
        client = genai.Client(api_key=k)
        HAS_GENAI = True
        # #region agent log
        try:
            import json
            with open(r"c:\Users\tyca7\Desktop\newbotV8AiD\newbotV8AiDJ-main\.cursor\debug.log", "a", encoding="utf-8") as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"gemini_init.py:14","message":"Gemini init: client created","data":{"has_genai":HAS_GENAI,"client_exists":client is not None},"timestamp":int(__import__("time").time()*1000)})+"\n")
        except: pass
        # #endregion
    else:
        # #region agent log
        try:
            import json
            with open(r"c:\Users\tyca7\Desktop\newbotV8AiD\newbotV8AiDJ-main\.cursor\debug.log", "a", encoding="utf-8") as f:
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
            with open(r"c:\Users\tyca7\Desktop\newbotV8AiD\newbotV8AiDJ-main\.cursor\debug.log", "a", encoding="utf-8") as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"gemini_init.py:18","message":"generate_smart: early return","data":{"has_genai":HAS_GENAI,"client_exists":client is not None},"timestamp":int(__import__("time").time()*1000)})+"\n")
        except: pass
        # #endregion
        return None
    for m in MODELS:
        try:
            result = client.models.generate_content(model=m, contents=prompt).text
            # #region agent log
            try:
                import json
                with open(r"c:\Users\tyca7\Desktop\newbotV8AiD\newbotV8AiDJ-main\.cursor\debug.log", "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"gemini_init.py:21","message":"generate_smart: success","data":{"model":m,"result_length":len(result) if result else 0},"timestamp":int(__import__("time").time()*1000)})+"\n")
            except: pass
            # #endregion
            return result
        except Exception as e:
            # #region agent log
            try:
                import json
                with open(r"c:\Users\tyca7\Desktop\newbotV8AiD\newbotV8AiDJ-main\.cursor\debug.log", "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"gemini_init.py:22","message":"generate_smart: model failed","data":{"model":m,"error":str(e)[:100]},"timestamp":int(__import__("time").time()*1000)})+"\n")
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