#!/usr/bin/env python3
"""
Тестирование AI провайдеров для DJ Aurora
Запуск: python test_ai_providers.py
"""

import os
import sys
import asyncio
import logging
from pathlib import Path

# Добавляем путь к проекту
sys.path.append(str(Path(__file__).parent))

import httpx
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_cloudflare():
    """Тестируем Cloudflare Workers AI"""
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    api_token = os.getenv("CLOUDFLARE_API_TOKEN")
    
    if not account_id or not api_token:
        logger.warning("CLOUDFLARE_ACCOUNT_ID или CLOUDFLARE_API_TOKEN не установлены")
        return False
    
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/meta/llama-3.1-8b-instruct"
    
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "@cf/meta/llama-3.1-8b-instruct",
        "messages": [
            {"role": "system", "content": "Ты DJ Aurora, веселая девушка-радиоведущая. Отвечай коротко."},
            {"role": "user", "content": "Привет! Как дела?"}
        ],
        "max_tokens": 50,
        "temperature": 0.7
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            
            logger.info(f"Cloudflare Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Cloudflare Response: {json.dumps(data, ensure_ascii=False)[:200]}")
                return True
            else:
                logger.error(f"Cloudflare Error: {response.text[:200]}")
                return False
    except Exception as e:
        logger.error(f"Cloudflare Exception: {e}")
        return False

async def test_groq():
    """Тестируем Groq API"""
    api_key = os.getenv("GROQ_API_KEY")
    
    if not api_key:
        logger.warning("GROQ_API_KEY не установлен")
        return False
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "llama-3.1-8b-instruct",
        "messages": [
            {"role": "system", "content": "Ты DJ Aurora. Отвечай коротко."},
            {"role": "user", "content": "Привет!"}
        ],
        "max_tokens": 50,
        "temperature": 0.7
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            
            logger.info(f"Groq Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Groq Response: {data['choices'][0]['message']['content'][:100]}")
                return True
            else:
                logger.error(f"Groq Error: {response.text[:200]}")
                return False
    except Exception as e:
        logger.error(f"Groq Exception: {e}")
        return False

async def test_openrouter():
    """Тестируем OpenRouter API"""
    api_key = os.getenv("OPENROUTER_API_KEY")
    
    if not api_key:
        logger.warning("OPENROUTER_API_KEY не установлен")
        return False
    
    url = "https://openrouter.ai/api/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://dj-aurora-bot.railway.app",
        "X-Title": "DJ Aurora Bot"
    }
    
    payload = {
        "model": "anthropic/claude-3-haiku",
        "messages": [
            {"role": "system", "content": "Короткий ответ."},
            {"role": "user", "content": "Тест"}
        ],
        "max_tokens": 30,
        "temperature": 0.7
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            
            logger.info(f"OpenRouter Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                logger.info(f"OpenRouter Response: {data['choices'][0]['message']['content'][:100]}")
                return True
            else:
                logger.error(f"OpenRouter Error: {response.text[:200]}")
                return False
    except Exception as e:
        logger.error(f"OpenRouter Exception: {e}")
        return False

async def main():
    """Запуск всех тестов"""
    print("=" * 50)
    print("Тестирование AI провайдеров DJ Aurora")
    print("=" * 50)
    
    # Проверяем переменные окружения
    print("\n🔍 Проверка переменных окружения:")
    vars_to_check = [
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_API_TOKEN", 
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "DEEPSEEK_API_KEY",
        "GEMINI_API_KEY"
    ]
    
    for var in vars_to_check:
        value = os.getenv(var)
        if value:
            print(f"  ✅ {var}: установлен")
        else:
            print(f"  ❌ {var}: не установлен")
    
    print("\n🧪 Тестирование провайдеров:")
    
    # Тестируем провайдеры
    providers = [
        ("Cloudflare", test_cloudflare),
        ("Groq", test_groq),
        ("OpenRouter", test_openrouter)
    ]
    
    results = []
    for name, test_func in providers:
        print(f"\n🔧 Тестирую {name}...")
        try:
            success = await test_func()
            status = "✅ УСПЕХ" if success else "❌ ОШИБКА"
            results.append((name, success))
            print(f"  {status}: {name}")
        except Exception as e:
            print(f"  ❌ ИСКЛЮЧЕНИЕ: {e}")
            results.append((name, False))
    
    print("\n" + "=" * 50)
    print("Итоговые результаты:")
    print("=" * 50)
    
    all_success = all(success for _, success in results)
    
    if all_success:
        print("🎉 Все провайдеры работают!")
        print("\nРекомендуемый порядок использования:")
        print("1. Cloudflare Workers AI (бесплатный, стабильный)")
        print("2. Groq (быстрый)")
        print("3. OpenRouter (если Cloudflare/Groq недоступны)")
    else:
        print("⚠️ Некоторые провайдеры не работают")
        print("\nРекомендации:")
        for name, success in results:
            if not success:
                if name == "Cloudflare":
                    print(f"- Cloudflare: получите Account ID и Token на dash.cloudflare.com")
                elif name == "Groq":
                    print(f"- Groq: получите ключ на console.groq.com")
                elif name == "OpenRouter":
                    print(f"- OpenRouter: получите ключ на openrouter.ai")
    
    return all_success

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)