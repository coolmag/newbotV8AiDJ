#!/usr/bin/env python3
"""
Простой тест Cloudflare Workers AI API
Запуск: python cloudflare_test.py
"""

import os
import httpx
import json
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

async def test_cloudflare_simple():
    """Простой тест Cloudflare API"""
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    api_token = os.getenv("CLOUDFLARE_API_TOKEN")
    
    if not account_id or not api_token:
        print("❌ Переменные окружения не установлены")
        print("   CLOUDFLARE_ACCOUNT_ID и CLOUDFLARE_API_TOKEN обязательны")
        return False
    
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/meta/llama-3.1-8b-instruct"
    
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }
    
    # Простое сообщение для теста
    payload = {
        "messages": [
            {"role": "system", "content": "Ты DJ Aurora. Отвечай очень кратко."},
            {"role": "user", "content": "Привет! Как дела?"}
        ],
        "max_tokens": 50,
        "temperature": 0.7
    }
    
    print(f"🔍 Тестирую Cloudflare API...")
    print(f"📝 URL: {url.split('/ai/run')[0]}/...")
    print(f"🔑 Account ID: {account_id[:10]}...")
    print(f"🔑 Token: {api_token[:10]}...")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            
            print(f"📊 Status Code: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ УСПЕХ!")
                print(f"📋 Ответ: {data}")
                
                # Извлекаем текст ответа
                if isinstance(data, dict):
                    if "result" in data and isinstance(data["result"], dict):
                        if "response" in data["result"]:
                            print(f"💬 Текст: {data['result']['response'][:200]}")
                        elif "text" in data["result"]:
                            print(f"💬 Текст: {data['result']['text'][:200]}")
                    elif "response" in data:
                        print(f"💬 Текст: {data['response'][:200]}")
                    elif "choices" in data and data["choices"]:
                        print(f"💬 Текст: {data['choices'][0]['message']['content'][:200]}")
                    else:
                        print(f"📋 Полный ответ: {json.dumps(data, ensure_ascii=False)[:500]}")
                return True
            else:
                print(f"❌ ОШИБКА: {response.status_code}")
                print(f"📋 Ответ сервера: {response.text[:500]}")
                return False
                
    except httpx.ConnectError as e:
        print(f"❌ Ошибка соединения: {e}")
        return False
    except httpx.TimeoutException:
        print(f"❌ Таймаут запроса (30 секунд)")
        return False
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
        return False

async def test_groq_simple():
    """Простой тест Groq API"""
    api_key = os.getenv("GROQ_API_KEY")
    
    if not api_key:
        print("⚠️ GROQ_API_KEY не установлен")
        return None
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "llama-3.1-8b-instruct",
        "messages": [
            {"role": "system", "content": "Ты DJ Aurora. Отвечай кратко."},
            {"role": "user", "content": "Тест"}
        ],
        "max_tokens": 30,
        "temperature": 0.7
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                return data['choices'][0]['message']['content'][:100]
            else:
                print(f"Groq Error: {response.status_code}")
                return None
    except Exception as e:
        print(f"Groq Exception: {e}")
        return None

async def main():
    """Основная функция"""
    print("=" * 60)
    print("🧪 ТЕСТИРОВАНИЕ AI ПРОВАЙДЕРОВ DJ AURORA")
    print("=" * 60)
    
    # Проверяем наличие ключей
    cloudflare_account = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    cloudflare_token = os.getenv("CLOUDFLARE_API_TOKEN")
    groq_key = os.getenv("GROQ_API_KEY")
    
    print("\n🔑 Проверка переменных окружения:")
    print(f"   CLOUDFLARE_ACCOUNT_ID: {'✅ установлен' if cloudflare_account else '❌ отсутствует'}")
    print(f"   CLOUDFLARE_API_TOKEN:  {'✅ установлен' if cloudflare_token else '❌ отсутствует'}")
    print(f"   GROQ_API_KEY:         {'✅ установлен' if groq_key else '❌ отсутствует'}")
    
    if cloudflare_account and cloudflare_token:
        print(f"\n🚀 Тестирую Cloudflare Workers AI...")
        cloudflare_success = await test_cloudflare_simple()
    else:
        print(f"\n⚠️ Cloudflare переменные не установлены. Инструкция:")
        print(f"   1. Создайте аккаунт на dash.cloudflare.com")
        print(f"   2. Найдите Account ID в профиле → API Tokens")
        print(f"   3. Создайте API Token с разрешениями 'Workers AI:Edit'")
        print(f"   4. Добавьте в .env файл:")
        print(f"      CLOUDFLARE_ACCOUNT_ID=ваш_id")
        print(f"      CLOUDFLARE_API_TOKEN=ваш_токен")
        cloudflare_success = False
    
    if groq_key:
        print(f"\n🚀 Тестирую Groq API...")
        groq_result = await test_groq_simple()
        if groq_result:
            print(f"✅ Groq работает!")
            print(f"💬 Ответ: {groq_result}")
        else:
            print(f"❌ Groq не отвечает")
    
    print("\n" + "=" * 60)
    
    if cloudflare_success:
        print("🎉 Cloudflare Workers AI работает корректно!")
        print("\n📋 Следующие шаги:")
        print("   1. Запустите бота: python main.py")
        print("   2. Проверьте команду /status в Telegram")
        print("   3. Протестируйте AI: /test_ai")
    else:
        print("⚠️ Для стабильной работы бота настройте:")
        print("   1. Cloudflare Workers AI (рекомендуется) ИЛИ")
        print("   2. Получите API ключи для других провайдеров")
        print("\n📚 Инструкция по настройке в CLOUDFLARE_SETUP.md")
    
    print("=" * 60)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())