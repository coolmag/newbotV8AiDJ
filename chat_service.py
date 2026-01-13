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

from ai_manager import AIManager
from ai_personas import get_system_prompt

logger = logging.getLogger(__name__)

chat_histories = defaultdict(lambda: deque(maxlen=10))
chat_modes = defaultdict(lambda: "default")

# ... (QuizManager class remains unchanged) ...
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
    async def get_response(chat_id: int, user_text: str, user_name: str) -> str:
        mode = chat_modes[chat_id]
        
        # === ПРОВЕРКА РЕЖИМА ВИКТОРИНЫ ===
        if mode == "quiz":
            if QuizManager.is_waiting_answer(chat_id):
                quiz_result = QuizManager.check_answer(chat_id, user_text)
                if quiz_result:
                    chat_histories[chat_id].append({"role": "user", "content": user_text})
                    chat_histories[chat_id].append({"role": "assistant", "content": quiz_result})
                    return quiz_result
            else: # Первый запуск викторины в режиме
                quiz_result = QuizManager.start_quiz(chat_id)
                chat_histories[chat_id].append({"role": "assistant", "content": quiz_result})
                return quiz_result

        # === ОБЫЧНЫЙ ЧАТ ===
        history = chat_histories[chat_id]
        
        # Собираем промпт из истории
        full_prompt = "\n".join([f"{m['role']}: {m['content']}" for m in history])
        full_prompt += f"\nuser: {user_name}: {user_text}"
        
        system_prompt = get_system_prompt(mode)

        # Вызываем централизованный AIManager
        res = await AIManager.get_ai_response(full_prompt, system_prompt=system_prompt)

        if res:
            logger.info(f"[ChatManager] AI response received, length: {len(res)}")
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": res})
            return res
        else:
            logger.warning("[ChatManager] All AI providers failed, returning fallback.")
            return "Сигнал нестабилен, но я тебя слышу! 📡"