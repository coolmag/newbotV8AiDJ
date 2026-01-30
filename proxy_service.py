import asyncio
import logging
import random
from pathlib import Path
from typing import List, Optional, Tuple

import httpx # Import httpx for testing proxy connection
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
            # Filter out Vless Reality proxies for now due to configuration issues
            self._proxies = [line.strip() for line in f if line.strip() and "security=reality" not in line.lower()]
        logger.info(f"Loaded {len(self._proxies)} compatible proxies from {self._proxy_list_path}")
    
    async def start_proxy(self, timeout: int = 15) -> bool:
        if self._active_proxy:
            logger.info("Proxy already running.")
            return True

        random.shuffle(self._proxies) # Randomize order to try different proxies
        
        for proxy_link in self._proxies:
            temp_proxy: Optional[V2RayProxy] = None
            try:
                logger.info(f"Attempting to start proxy: {proxy_link[:50]}...")
                
                temp_proxy = V2RayProxy(proxy_link)
                
                # Wait for socks_proxy_url to become available
                start_time = asyncio.get_event_loop().time()
                test_passed = False
                error_message = "Timed out waiting for proxy to become ready."

                while asyncio.get_event_loop().time() - start_time < timeout:
                    if getattr(temp_proxy, 'socks_proxy_url', None):
                        # Test the proxy connection
                        success, test_error_msg = await self._test_proxy_connection(temp_proxy.socks_proxy_url)
                        if success:
                            self._active_proxy = temp_proxy
                            self._active_proxy_url = self._active_proxy.socks_proxy_url
                            logger.info(f"Successfully started and tested proxy on {self._active_proxy_url}")
                            test_passed = True
                            break
                        else:
                            error_message = f"Failed connection test: {test_error_msg}"
                            logger.warning(f"Proxy {proxy_link[:50]}... started but {error_message}")
                            break # Break from inner loop to try next proxy
                    await asyncio.sleep(1) # Check every second
                
                if test_passed:
                    return True
                else:
                    logger.warning(f"Proxy {proxy_link[:50]}... did not become ready within {timeout} seconds. {error_message}")

            except Exception as e:
                logger.error(f"Failed to start proxy {proxy_link[:50]}...: {e}")
            finally:
                if temp_proxy and temp_proxy != self._active_proxy: # Only stop if it's not the active one
                    logger.debug(f"Stopping failed/untested proxy {proxy_link[:50]}...")
                    temp_proxy.stop()
                
        logger.error("Failed to start any V2Ray proxy from the list.")
        return False

    async def _test_proxy_connection(self, proxy_url: str) -> Tuple[bool, Optional[str]]:
        """Tests the proxy connection by making a request to a known reliable service.
        Returns (True, None) on success, or (False, error_message) on failure."""
        try:
            async with httpx.AsyncClient(proxies={"http://": proxy_url, "https://": proxy_url}, timeout=20) as client:
                response = await client.get("https://www.google.com", follow_redirects=True)
                response.raise_for_status() # Raise an exception for bad status codes
                logger.debug(f"Proxy test to google.com successful via {proxy_url}")
                return True, None
        except httpx.RequestError as e:
            error_details = f"{e.__class__.__name__}: {e}"
            if e.__cause__:
                error_details += f" (Cause: {e.__cause__.__class__.__name__}: {e.__cause__})"
            return False, error_details
        except Exception as e:
            return False, f"Unexpected error during proxy test: {e}"

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

