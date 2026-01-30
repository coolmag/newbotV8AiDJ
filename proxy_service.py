import asyncio
import logging
import random
from pathlib import Path
from typing import List, Optional, Tuple

import httpx
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

    async def start_proxy(self, timeout: int = 30) -> bool:
        """
        Starts a V2Ray proxy. 
        Timeout increased to 30s to allow slow connections to stabilize.
        """
        if self._active_proxy:
            logger.info(f"Proxy already running on {self._active_proxy_url}")
            return True

        random.shuffle(self._proxies)
        
        for proxy_link in self._proxies:
            temp_proxy: Optional[V2RayProxy] = None
            try:
                logger.info(f"🚀 Attempting to start proxy: {proxy_link[:40]}...")
                temp_proxy = V2RayProxy(proxy_link)
                
                # Wait loop
                start_time = asyncio.get_event_loop().time()
                test_passed = False
                last_error = ""

                while asyncio.get_event_loop().time() - start_time < timeout:
                    if getattr(temp_proxy, 'socks_proxy_url', None):
                        proxy_url = temp_proxy.socks_proxy_url
                        
                        # Делаем паузу перед тестом, чтобы V2Ray успел поднять туннель
                        await asyncio.sleep(2) 
                        
                        logger.debug(f"Testing connectivity via {proxy_url}...")
                        success, error_msg = await self._test_proxy_connection(proxy_url)
                        
                        if success:
                            self._active_proxy = temp_proxy
                            self._active_proxy_url = proxy_url
                            logger.info(f"✅ Proxy UP and running: {self._active_proxy_url}")
                            test_passed = True
                            break
                        else:
                            last_error = error_msg
                            logger.warning(f"⚠️ Proxy started but failed test: {error_msg}. Retrying...")
                    
                    await asyncio.sleep(2)

                if test_passed:
                    return True
                
                # Если тайм-аут вышел
                logger.error(f"❌ Proxy {proxy_link[:30]} timed out ({timeout}s). Last error: {last_error}")
                if temp_proxy: temp_proxy.stop()

            except Exception as e:
                logger.error(f"🔥 Critical error starting proxy: {e}")
                if temp_proxy: temp_proxy.stop()
        
        logger.error("🚫 All proxies failed to start or connect.")
        return False

    async def _test_proxy_connection(self, proxy_url: str) -> Tuple[bool, Optional[str]]:
        """
        Tests connection using Cloudflare's connectivity check (lighter than Google).
        """
        try:
            # Используем http://cp.cloudflare.com/generate_204 - это очень легкий чек
            target_url = "http://cp.cloudflare.com/generate_204"
            
            async with httpx.AsyncClient(
                proxies={"http://": proxy_url, "https://": proxy_url}, 
                timeout=10.0,
                verify=False # Игнорируем ошибки SSL (важно для V2Ray)
            ) as client:
                
                response = await client.get(target_url)
                
                if response.status_code == 204 or response.status_code == 200:
                    return True, None
                else:
                    return False, f"Status code: {response.status_code}"

        except httpx.ConnectTimeout:
            return False, "ConnectTimeout"
        except httpx.ReadTimeout:
            return False, "ReadTimeout"
        except httpx.ProxyError as e:
            return False, f"ProxyError: {e}"
        except Exception as e:
            return False, f"Error: {str(e)[:50]}"

    def stop_proxy(self):
        if self._active_proxy:
            logger.info(f"🛑 Stopping active proxy on {self._active_proxy_url}")
            self._active_proxy.stop()
            self._active_proxy = None
            self._active_proxy_url = None
        else:
            logger.info("No active proxy to stop.")

    @property
    def active_proxy_url(self) -> Optional[str]:
        return self._active_proxy_url