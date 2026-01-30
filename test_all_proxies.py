import asyncio
import logging
import random
from pathlib import Path
from typing import List, Optional, Tuple

import httpx
from v2ray2proxy import V2RayProxy

# Configure logging for the script
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

PROXY_LIST_PATH = Path("hiddify_compatible_v2ray_proxies.txt")
TEST_TIMEOUT = 20 # Seconds for httpx connection test
PROXY_STARTUP_TIMEOUT = 60 # Seconds to wait for V2RayProxy to become ready

async def _test_proxy_connection(proxy_url: str) -> Tuple[bool, Optional[str]]:
    """Tests the proxy connection by making a request to a known reliable service.
    Returns (True, None) on success, or (False, error_message) on failure."""
    try:
        async with httpx.AsyncClient(proxies={"http://": proxy_url, "https://": proxy_url}, timeout=TEST_TIMEOUT) as client:
            response = await client.get("https://www.google.com", follow_redirects=True)
            response.raise_for_status()
            return True, None
    except httpx.RequestError as e:
        error_details = f"{e.__class__.__name__}: {e}"
        if e.__cause__:
            error_details += f" (Cause: {e.__cause__.__class__.__name__}: {e.__cause__})"
        return False, error_details
    except Exception as e:
        return False, f"Unexpected error during proxy test: {e}"

async def test_single_proxy(proxy_link: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Tests a single proxy link.
    Returns (is_working, socks_proxy_url, error_message).
    """
    temp_proxy: Optional[V2RayProxy] = None
    socks_url: Optional[str] = None
    # Initialize with a default message if socks_proxy_url never becomes available
    last_test_error: Optional[str] = None 

    try:
        temp_proxy = V2RayProxy(proxy_link)
        
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < PROXY_STARTUP_TIMEOUT:
            if getattr(temp_proxy, 'socks_proxy_url', None):
                socks_url = temp_proxy.socks_proxy_url
                success, test_error_msg = await _test_proxy_connection(socks_url)
                if success:
                    return True, socks_url, None
                else:
                    last_test_error = f"Connection test failed: {test_error_msg}"
                    # If connection test fails, we have a specific reason, so break and report it.
                    break 
            await asyncio.sleep(1)
        
        # If we reach here, either socks_url was never exposed, or it failed the connection test.
        if last_test_error:
            return False, None, last_test_error
        else:
            return False, None, f"Proxy did not expose socks_proxy_url within {PROXY_STARTUP_TIMEOUT} seconds."

    except Exception as e:
        return False, None, f"Failed to start V2RayProxy: {e}"
    finally:
        if temp_proxy:
            temp_proxy.stop()

async def main():
    if not PROXY_LIST_PATH.exists():
        logger.error(f"Proxy list file not found: {PROXY_LIST_PATH}")
        return

    with open(PROXY_LIST_PATH, 'r', encoding='utf-8') as f:
        all_proxies = [line.strip() for line in f if line.strip()]

    # Filter out Vless Reality proxies for now due to known configuration issues
    compatible_proxies = [p for p in all_proxies if "security=reality" not in p.lower()]
    
    logger.info(f"Loaded {len(all_proxies)} proxies, {len(compatible_proxies)} compatible after filtering 'security=reality'.")
    
    working_proxies: List[str] = []
    
    for i, proxy_link in enumerate(compatible_proxies):
        logger.info(f"[{i+1}/{len(compatible_proxies)}] Testing proxy: {proxy_link[:80]}...")
        is_working, socks_url, error_message = await test_single_proxy(proxy_link)
        
        if is_working:
            working_proxies.append(proxy_link)
            logger.info(f"🟢 Working proxy found: {proxy_link[:80]} (via {socks_url})")
        else:
            logger.warning(f"🔴 Failed to test proxy: {proxy_link[:80]} - {error_message}")
            
    logger.info("\n--- Test Summary ---")
    if working_proxies:
        logger.info(f"✅ Found {len(working_proxies)} working proxies:")
        for proxy in working_proxies:
            logger.info(f"  - {proxy}")
        
        # Optionally write working proxies to a new file
        with open("working_v2ray_proxies.txt", "w", encoding="utf-8") as f:
            for proxy in working_proxies:
                f.write(f"{proxy}\n")
        logger.info(f"Working proxies saved to working_v2ray_proxies.txt")

    else:
        logger.error("❌ No working proxies found in the list.")

if __name__ == "__main__":
    asyncio.run(main())
