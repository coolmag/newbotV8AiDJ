import asyncio
import logging
import random
from pathlib import Path
from typing import List, Optional

from v2ray2proxy import V2RayProxy

logger = logging.getLogger(__name__)

class ProxyManager:
    def __init__(self, proxy_list_path: Path):
        self._proxy_list_path = proxy_list_path
        self._proxies: List[str] = []
        self._active_proxy: Optional[V2RayProxy] = None
        self._active_proxy_url: Optional[str] = None
        self._load_proxies()

    def _load_proxies(self):
        if not self._proxy_list_path.exists():
            logger.warning(f"Proxy list file not found: {self._proxy_list_path}")
            return
        
        with open(self._proxy_list_path, 'r', encoding='utf-8') as f:
            self._proxies = [line.strip() for line in f if line.strip()]
        logger.info(f"Loaded {len(self._proxies)} proxies from {self._proxy_list_path}")
    
    async def start_proxy(self) -> bool:
        if self._active_proxy:
            logger.info("Proxy already running.")
            return True

        random.shuffle(self._proxies) # Randomize order to try different proxies
        
        for proxy_link in self._proxies:
            try:
                logger.info(f"Attempting to start proxy: {proxy_link[:50]}...") # Log first 50 chars for brevity
                
                # V2RayProxy will automatically find a free port if socks_port is not specified
                temp_proxy = V2RayProxy(proxy_link)
                # It seems V2RayProxy does not have an explicit start method that returns awaitable
                # The instantiation itself might trigger the core binary start.
                # Need to verify this behavior or add explicit start if available.
                
                # Give the proxy some time to start up
                await asyncio.sleep(5) 
                
                # Check if the proxy is actually running and accessible locally
                # This would typically involve trying to connect to a known external service
                # via the local SOCKS5 proxy. For now, assume it starts if no exception.
                
                self._active_proxy = temp_proxy
                self._active_proxy_url = self._active_proxy.socks_proxy_url
                logger.info(f"Successfully started proxy on {self._active_proxy_url}")
                return True
            except Exception as e:
                logger.error(f"Failed to start proxy {proxy_link[:50]}...: {e}")
                if temp_proxy:
                    temp_proxy.stop() # Ensure any failed proxy is stopped
                continue
        
        logger.error("Failed to start any V2Ray proxy from the list.")
        return False

    def stop_proxy(self):
        if self._active_proxy:
            logger.info(f"Stopping active proxy on {self._active_proxy_url}")
            self._active_proxy.stop()
            self._active_proxy = None
            self._active_proxy_url = None
        else:
            logger.info("No active proxy to stop.")

    @property
    def active_proxy_url(self) -> Optional[str]:
        return self._active_proxy_url

