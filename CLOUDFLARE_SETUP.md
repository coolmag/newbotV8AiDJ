# ИНСТРУКЦИЯ ПО ПОЛУЧЕНИЮ БЕСПЛАТНОГО CLOUDFLARE WORKERS AI API
# ===========================================================

## Шаг 1: Регистрация на Cloudflare
1. Перейдите на https://dash.cloudflare.com/
2. Зарегистрируйте новый аккаунт (бесплатно)
3. Подтвердите email

## Шаг 2: Получение Account ID
1. В левом меню выберите "Workers & Pages"
2. В правом верхнем углу нажмите на свой профиль → "My Profile"
3. В разделе "API Tokens" найдите "Account ID"
4. Скопируйте 32-символьный ID (например: `1234567890abcdef1234567890abcdef`)

## Шаг 3: Создание API Token
1. В том же разделе "API Tokens" нажмите "Create Token"
2. Выберите шаблон "Edit Cloudflare Workers"
3. Настройте разрешения:
   - Account: Workers AI:Edit ✅
   - Account: Workers Scripts:Edit ✅
4. Нажмите "Continue to summary"
5. Нажмите "Create Token"
6. СКОПИРУЙТЕ ТОКЕН (он покажется только один раз!)

## Шаг 4: Добавление в Railway
1. Откройте Railway Dashboard для своего проекта
2. Перейдите в "Settings" → "Variables"
3. Добавьте переменные:
   ```
   CLOUDFLARE_ACCOUNT_ID=your_account_id
   CLOUDFLARE_API_TOKEN=your_api_token
   ```

## Шаг 5: Проверка работы
После добавления переменных:
1. Railway перезапустит приложение
2. Проверьте команду `/status` в боте
3. Должна появиться строчка: "[AI Config] Cloudflare is ACTIVE (free tier)"

## Преимущества Cloudflare Workers AI:
- ✅ 100,000 запросов БЕСПЛАТНО в день
- ✅ Нет лимита по времени использования
- ✅ Быстрые ответы (< 1 сек)
- ✅ Стабильное API
- ✅ Не требует привязки кредитной карты
- ✅ Поддерживает модели Llama 3.1, Mistral и другие

## Если Cloudflare недоступен:
1. Получите ключ **Groq**: https://console.groq.com/keys
2. Добавьте в Railway: `GROQ_API_KEY=your_key`
3. Проверьте `/status`

## Тестирование
После добавления ключей, используйте команду `/test_ai` в боте для проверки соединения.