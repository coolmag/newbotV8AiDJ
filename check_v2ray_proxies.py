import logging
import os
import threading
import queue
import requests
from v2ray2proxy import V2RayProxy

# --- Configuration ---
INPUT_FILE = 'hiddify_compatible_v2ray_proxies.txt'
OUTPUT_FILE = 'working_v2ray_proxies.txt'
NUM_THREADS = 10
# Use a reliable and fast-to-respond URL for testing
TEST_URL = 'http://cp.cloudflare.com/'
# Timeout for the actual connection test via the proxy
REQUEST_TIMEOUT = 8

# --- Logging Setup ---
# Clear the log file at the start of each run
if os.path.exists("proxy_check.log"):
    os.remove("proxy_check.log")

logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("proxy_check.log"),
        logging.StreamHandler()
    ]
)

def check_proxy_worker(q, working_proxies_list):
    """Pulls proxy links from a queue and tests them by making a web request."""
    while not q.empty():
        proxy_link = q.get()
        if not proxy_link:
            q.task_done()
            continue

        logging.info(f"Processing: {proxy_link[:40]}...")
        proxy_instance = None
        try:
            # This starts the xray.exe process with the given config
            proxy_instance = V2RayProxy(proxy_link)
            
            # If xray.exe starts, the library provides local proxy URLs
            proxies = {
                "http": proxy_instance.http_proxy_url,
                "https": proxy_instance.http_proxy_url
            }
            
            logging.info(f"Testing connectivity via {proxy_instance.http_proxy_url}...")
            
            # Make the actual test request
            response = requests.get(TEST_URL, proxies=proxies, timeout=REQUEST_TIMEOUT, allow_redirects=False)
            
            # Cloudflare's test page returns a 204 No Content on success
            if 200 <= response.status_code < 300:
                logging.info(f"  -> SUCCESS! Proxy is working. Status: {response.status_code}")
                working_proxies_list.append(proxy_link)
            else:
                logging.warning(f"  -> FAILED. Received unexpected status code: {response.status_code}")

        except requests.exceptions.RequestException as e:
            logging.warning(f"  -> FAILED. Connection error: {e.__class__.__name__}")
        except Exception as e:
            # This will catch errors from V2RayProxy initialization (e.g., bad configs)
            logging.error(f"  -> ERROR. An exception occurred: {e}")
        finally:
            # Crucial: always stop the xray.exe process
            if proxy_instance:
                proxy_instance.stop()
            q.task_done()

def main():
    """
    Main function to read, check, and save proxy links using multiple threads.
    """
    if not os.path.exists(INPUT_FILE):
        logging.error(f"Input file not found: {INPUT_FILE}")
        print(f"Ошибка: Файл с прокси не найден: {os.path.abspath(INPUT_FILE)}")
        return

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        proxy_links = [line.strip() for line in f if line.strip()]

    if not proxy_links:
        logging.info("No proxies found in input file.")
        print("Файл с прокси пуст.")
        return

    total_proxies = len(proxy_links)
    logging.info(f"Found {total_proxies} proxies. Starting checks with {NUM_THREADS} threads...")
    print(f"Найдено {total_proxies} прокси. Запускаю проверку в {NUM_THREADS} потоков...")

    proxy_queue = queue.Queue()
    for link in proxy_links:
        proxy_queue.put(link)

    # Use a simple list for collecting results. It's thread-safe for appends.
    working_proxies = []
    
    threads = []
    for i in range(NUM_THREADS):
        thread = threading.Thread(target=check_proxy_worker, args=(proxy_queue, working_proxies), name=f"Checker-{i+1}")
        thread.start()
        threads.append(thread)

    # Wait for the queue to be fully processed
    proxy_queue.join()

    # Wait for all threads to finish their current task
    for thread in threads:
        thread.join()

    logging.info(f"Finished. Found {len(working_proxies)} working out of {total_proxies}.")
    print(f"\nПроверка завершена. Найдено {len(working_proxies)} рабочих прокси из {total_proxies}.")

    # Write the working proxies to the output file
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        if working_proxies:
            for proxy in sorted(working_proxies):
                f.write(proxy + '\n')
        else:
            # Write a comment if no proxies were found to be working
            f.write("# No working proxies found.\n")

    logging.info(f"Working proxies saved to {OUTPUT_FILE}")
    print(f"Рабочие прокси сохранены в файл: {os.path.abspath(OUTPUT_FILE)}")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nПроверка прервана пользователем.")
    except Exception as e:
        logging.critical(f"A critical error occurred: {e}", exc_info=True)
        print(f"Произошла критическая ошибка: {e}")