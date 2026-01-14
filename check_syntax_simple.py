#!/usr/bin/env python3
"""
Простой скрипт для проверки синтаксиса всех Python файлов в проекте
"""

import sys
import os
import py_compile

def check_python_file(filepath):
    """Проверяет синтаксис Python файла"""
    try:
        py_compile.compile(filepath, doraise=True)
        return True, None
    except py_compile.PyCompileError as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)

def main():
    print("🔍 Проверка синтаксиса Python файлов...")
    print("=" * 60)
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Основные файлы проекта
    python_files = [
        "main.py",
        "ai_config.py",
        "ai_manager.py",
        "ai_personas.py",
        "chat_service.py",
        "handlers.py",
        "nlp.py",
        "radio.py",
        "youtube.py",
        "gemini_init.py",
        "config.py",
        "cache_service.py",
        "catalog.py",
        "keyboards.py",
        "models.py",
        "logging_setup.py"
    ]
    
    all_ok = True
    errors = []
    
    for filename in python_files:
        filepath = os.path.join(current_dir, filename)
        if not os.path.exists(filepath):
            print(f"⚠️  {filename}: файл не найден")
            continue
            
        success, error = check_python_file(filepath)
        if success:
            print(f"✅ {filename}: OK")
        else:
            print(f"❌ {filename}: ОШИБКА")
            print(f"   {error}")
            errors.append((filename, error))
            all_ok = False
    
    print("\n" + "=" * 60)
    if all_ok:
        print("🎉 Все файлы прошли проверку синтаксиса!")
        return 0
    else:
        print(f"⚠️ Найдены ошибки в {len(errors)} файлах:")
        for filename, error in errors:
            print(f"\n{filename}:")
            print(f"  {error}")
        return 1

if __name__ == "__main__":
    sys.exit(main())