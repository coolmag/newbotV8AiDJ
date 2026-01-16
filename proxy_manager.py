import logging
import random
from pathlib import Path
from typing import List, Optional
import glob

logger = logging.getLogger(__name__)

class ProxyManager:
    def __init__(self, project_root: Path):
        self._project_root = project_root
        self._proxies: List[str] = []
        self._load_proxies()

    def _load_proxies(self):
        """Загружает прокси из файлов data*.txt в корне проекта."""
        self._proxies = []
        
        # Находим все файлы data*.txt в корне
        proxy_files = glob.glob(str(self._project_root / "data*.txt"))

        if not proxy_files:
            logger.warning("No proxy files (data*.txt) found in the project root.")
            return

        for path_str in proxy_files:
            path = Path(path_str)
            try:
                with open(path, "r") as f:
                    for line in f:
                        proxy = line.strip()
                        if proxy and "://" in proxy: # Убедимся, что строка похожа на URL
                            self._proxies.append(proxy)
            except Exception as e:
                logger.error(f"Failed to load proxies from {path.name}: {e}")

        if not self._proxies:
            logger.warning("Proxy files were found, but no valid proxies could be loaded.")
            return

        random.shuffle(self._proxies)
        logger.info(f"Loaded and shuffled {len(self._proxies)} proxies from {len(proxy_files)} files.")

    def get_proxy(self) -> Optional[str]:
        """Возвращает следующий прокси из списка."""
        if not self._proxies:
            logger.info("Proxy list is empty. Reloading proxies...")
            self._load_proxies()
        
        if not self._proxies:
            return None
            
        return self._proxies.pop(0)

    def report_dead_proxy(self, proxy: str):
        logger.warning(f"Proxy {proxy} reported as dead. It's already removed from the current session list.")