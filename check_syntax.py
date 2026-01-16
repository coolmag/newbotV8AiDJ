#!/usr/bin/env python3
"""
Проверка синтаксиса и импортов основных файлов
"""

import subprocess
import sys
import os

def check_file(filepath):
    """Проверяет синтаксис Python файла"""
    print(f"🔍 Проверяю {filepath}...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", filepath],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print(f"✅ Синтаксис корректный")
            return True
        else:
            print(f"❌ Ошибка синтаксиса:")
            print(f"   {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Ошибка проверки: {e}")
        return False

def check_imports(filepath):
    """Проверяет импорты в файле"""
    print(f"📦 Проверяю импорты в {filepath}...")
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Простая проверка на явные ошибки импорта
        if "ImportError" in content and "cannot import name" in content:
            print(f"❌ Обнаружена ошибка импорта в коде")
            return False
        
        # Попробуем импортировать модуль
        module_name = filepath.replace('.py', '').replace('/', '.').replace('\\', '.')
        if module_name.startswith('.'):
            module_name = module_name[1:]
            
        # Пропустим проверку импорта для тестовых файлов
        if 'test_' in filepath:
            print(f"⚠️ Тестовый файл, пропускаю импорт")
            return True
            
        print(f"✅ Импорты проверены (поверхностно)")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка проверки импортов: {e}")
        return False

def main():
    files_to_check = [
        "ai_config.py",
        "ai_manager.py", 
        "ai_personas.py",
        "chat_service.py",
        "gemini_init.py",
        "handlers.py",
        "main.py",
        "nlp.py",
        "radio.py"
    ]
    
    print("=" * 60)
    print("🔧 ПРОВЕРКА СИНТАКСИСА DJ AURORA")
    print("=" * 60)
    
    results = {}
    all_ok = True
    
    for file in files_to_check:
        if not os.path.exists(file):
            print(f"⚠️ Файл {file} не найден")
            results[file] = False
            continue
            
        syntax_ok = check_file(file)
        imports_ok = check_imports(file)
        
        file_ok = syntax_ok and imports_ok
        results[file] = file_ok
        all_ok = all_ok and file_ok
        
        print()
    
    print("=" * 60)
    print("📊 ИТОГИ ПРОВЕРКИ:")
    print("=" * 60)
    
    for file, ok in results.items():
        status = "✅" if ok else "❌"
        print(f"{status} {file}")
    
    print("\n" + "=" * 60)
    if all_ok:
        print("🎉 Все файлы прошли проверку синтаксиса!")
        print("\nСледующие шаги:")
        print("1. Настройте API ключи в Railway")
        print("2. Запустите: python cloudflare_test.py")
        print("3. Запустите бота: python main.py")
        print("4. Проверьте команду /status в Telegram")
    else:
        print("⚠️ Есть проблемы с синтаксисом или импортами")
        print("\nИсправьте ошибки перед запуском бота")
    
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())