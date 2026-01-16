import asyncio
import glob
from pathlib import Path
import logging
from curl_cffi.requests import AsyncSession

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Константы
PROJECT_ROOT = Path(__file__).parent
INPUT_FILES_PATTERN = str(PROJECT_ROOT / "data*.txt")
OUTPUT_FILE = PROJECT_ROOT / "working_proxies.txt"
CHECK_URL = "https://www.google.com"
TIMEOUT = 7  # Таймаут для одного прокси в секундах
CONCURRENCY_LIMIT = 200  # Количество одновременных проверок

async def check_proxy(session: AsyncSession, proxy: str):
    """Проверяет один прокси. Возвращает прокси в случае успеха, иначе None."""
    try:
        response = await session.get(CHECK_URL, proxy=proxy, timeout=TIMEOUT)
        if 200 <= response.status_code < 300:
            logging.info(f"SUCCESS: {proxy} - Status: {response.status_code}")
            return proxy
        else:
            logging.warning(f"FAIL: {proxy} - Status: {response.status_code}")
            return None
    except Exception as e:
        # Уменьшаем уровень логирования для "мусорных" ошибок
        logging.debug(f"ERROR: {proxy} - {str(e)}")
        return None

async def main():
    """Основная функция для чтения, проверки и записи прокси."""
    # 1. Читаем все прокси из файлов
    all_proxies = set()
    input_files = glob.glob(INPUT_FILES_PATTERN)
    if not input_files:
        logging.error(f"No input files found matching '{INPUT_FILES_PATTERN}'. Exiting.")
        return
        
    logging.info(f"Found {len(input_files)} proxy files: {[Path(f).name for f in input_files]}")

    for file_path in input_files:
        with open(file_path, "r") as f:
            for line in f:
                proxy = line.strip()
                if proxy and "://" in proxy:
                    all_proxies.add(proxy)

    proxies_to_check = list(all_proxies)
    total_proxies = len(proxies_to_check)
    logging.info(f"Found {total_proxies} unique proxies to check.")

    # 2. Проверяем прокси пачками
    working_proxies = []
    
    async with AsyncSession(impersonate="chrome110") as session:
        for i in range(0, total_proxies, CONCURRENCY_LIMIT):
            batch = proxies_to_check[i:i + CONCURRENCY_LIMIT]
            logging.info(f"Checking batch {i // CONCURRENCY_LIMIT + 1}/{(total_proxies + CONCURRENCY_LIMIT - 1) // CONCURRENCY_LIMIT} (size: {len(batch)})...")
            
            tasks = [check_proxy(session, proxy) for proxy in batch]
            results = await asyncio.gather(*tasks)
            
            for result in results:
                if result:
                    working_proxies.append(result)
            
            logging.info(f"Batch finished. Total working proxies so far: {len(working_proxies)}")

    # 3. Записываем рабочие прокси в файл
    if working_proxies:
        logging.info(f"Found {len(working_proxies)} working proxies in total.")
        with open(OUTPUT_FILE, "w") as f:
            for proxy in working_proxies:
                f.write(proxy + "\n")
        logging.info(f"Successfully saved working proxies to '{OUTPUT_FILE.name}'")
    else:
        logging.warning("No working proxies found after checking all candidates.")

if __name__ == "__main__":
    asyncio.run(main())
