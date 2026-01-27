#!/usr/bin/env python3
"""
 Instance Tester - Find working YouTube API proxies
Run: python test_instances.py
"""

import asyncio
import httpx
import time

# Test video ID (Rick Astley - short, always available)
TEST_VIDEO = "dQw4w9WgXcQ"

INVIDIOUS_INSTANCES = [
    "https://vid.puffyan.us",
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://invidious.privacydev.net",
    "https://yt.artemislena.eu",
    "https://invidious.lunar.icu",
    "https://invidious.protokolla.fi",
    "https://iv.melmac.space",
    "https://invidious.private.coffee",
    "https://invidious.drgns.space",
    "https://inv.tux.pizza",
    "https://invidious.jing.rocks",
    "https://invidious.einfachzocken.eu",
    "https://invidious.projectsegfau.lt",
    "https://invidious.perennialte.ch",
    "https://invidious.materialio.us",
    "https://yewtu.be",
    "https://inv.vern.cc",
    "https://invidious.slipfox.xyz",
    "https://invidious.io.lol",
]

PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.adminforge.de",
    "https://api.piped.yt",
    "https://pipedapi.darkness.services",
    "https://pipedapi.in.projectsegfau.lt",
    "https://pipedapi.leptons.xyz",
    "https://pipedapi.r4fo.com",
    "https://pa.il.ax",
    "https://api.piped.private.coffee",
    "https://pipedapi.drgns.space",
    "https://pipedapi.moomoo.me",
    "https://piped-api.lunar.icu",
]

COBALT_INSTANCES = [
    "https://api.cobalt.tools",
    "https://cobalt-api.ayo.tf",
    "https://co.eepy.today",
    "https://cobalt.api.timelessnesses.me",
    "https://api.co.wukko.me",
]


async def test_invidious(url: str) -> dict:
    try:
        start = time.time()
        async with httpx.AsyncClient(timeout=10.0, verify=False, follow_redirects=True) as client:
            resp = await client.get(f"{url}/api/v1/videos/{TEST_VIDEO}")
            elapsed = time.time() - start
            
            if resp.status_code != 200:
                return {"url": url, "status": "FAIL", "reason": f"HTTP {resp.status_code}"}
            
            data = resp.json()
            formats = data.get("adaptiveFormats", [])
            audio = [f for f in formats if f.get("type", "").startswith("audio/")]
            
            if not audio:
                return {"url": url, "status": "FAIL", "reason": "No audio formats"}
            
            return {"url": url, "status": "OK", "time": f"{elapsed:.1f}s"}
    except Exception as e:
        return {"url": url, "status": "FAIL", "reason": str(e)[:50]}


async def test_piped(url: str) -> dict:
    try:
        start = time.time()
        async with httpx.AsyncClient(timeout=10.0, verify=False, follow_redirects=True) as client:
            resp = await client.get(f"{url}/streams/{TEST_VIDEO}")
            elapsed = time.time() - start
            
            if resp.status_code != 200:
                return {"url": url, "status": "FAIL", "reason": f"HTTP {resp.status_code}"}
            
            data = resp.json()
            if data.get("error"):
                return {"url": url, "status": "FAIL", "reason": data.get("message", "API error")}
            
            return {"url": url, "status": "OK", "time": f"{elapsed:.1f}s"}
    except Exception as e:
        return {"url": url, "status": "FAIL", "reason": str(e)[:50]}


async def test_cobalt(url: str) -> dict:
    try:
        start = time.time()
        headers = {"Accept": "application/json", "Content-Type": "application/json", "Origin": "https://cobalt.tools", "Referer": "https://cobalt.tools/"}
        payload = {"url": f"https://www.youtube.com/watch?v={TEST_VIDEO}", "downloadMode": "audio"}
        
        async with httpx.AsyncClient(timeout=15.0, verify=False, follow_redirects=True) as client:
            resp = await client.post(url, json=payload, headers=headers)
            elapsed = time.time() - start
            
            if resp.status_code not in (200, 201):
                # Try v7 fallback
                resp = await client.post(f"{url}/api/json", json={"url": payload["url"], "isAudioOnly": True}, headers=headers)
            
            if resp.status_code not in (200, 201):
                return {"url": url, "status": "FAIL", "reason": f"HTTP {resp.status_code}"}
            
            return {"url": url, "status": "OK", "time": f"{elapsed:.1f}s"}
    except Exception as e:
        return {"url": url, "status": "FAIL", "reason": str(e)[:50]}


async def main():
    print("SEARCHING FOR WORKING INSTANCES...")
    
    tasks = []
    tasks.extend([test_invidious(u) for u in INVIDIOUS_INSTANCES])
    tasks.extend([test_piped(u) for u in PIPED_INSTANCES])
    tasks.extend([test_cobalt(u) for u in COBALT_INSTANCES])
    
    results = await asyncio.gather(*tasks)
    
    inv_ok = [r["url"] for r in results if r["status"] == "OK" and r["url"] in INVIDIOUS_INSTANCES]
    piped_ok = [r["url"] for r in results if r["status"] == "OK" and r["url"] in PIPED_INSTANCES]
    cobalt_ok = [r["url"] for r in results if r["status"] == "OK" and r["url"] in COBALT_INSTANCES]
    
    print(f"\nINVIDIOUS_INSTANCES={','.join(inv_ok)}")
    print(f"PIPED_INSTANCES={','.join(piped_ok)}")
    print(f"COBALT_INSTANCES={','.join(cobalt_ok)}")

if __name__ == "__main__":
    asyncio.run(main())
