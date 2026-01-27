from pathlib import Path
from typing import List, Any, Optional, Union
from functools import lru_cache
import logging
import os
import json

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, ValidationInfo

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )
    
    BOT_TOKEN: str 
    WEBHOOK_URL: str 
    BASE_URL: str = ""
    ADMIN_IDS: str = ""
    
    # Auth
    COOKIES_CONTENT: str = ""
    PO_TOKEN: Optional[str] = None 
    
    # Proxy
    PROXY_URL: Optional[str] = None
    
    # Spotify
    SPOTIFY_CLIENT_ID: Optional[str] = None
    SPOTIFY_CLIENT_SECRET: Optional[str] = None
    
    # API Pools
    COBALT_INSTANCES: Union[List[str], str, None] = None
    PIPED_INSTANCES: Union[List[str], str, None] = None

    GEMINI_API_KEY: Optional[str] = None
    VK_LOGIN: Optional[str] = None
    VK_PASSWORD: Optional[str] = None
    
    ADMIN_ID_LIST: List[int] = []
    
    BASE_DIR: Path = Path(__file__).resolve().parent
    DOWNLOADS_DIR: Path = BASE_DIR / "downloads"
    TEMP_AUDIO_DIR: Path = BASE_DIR / "temp_audio"
    CACHE_DB_PATH: Path = BASE_DIR / "cache.db"
    COOKIES_FILE: Path = BASE_DIR / "cookies.txt"
    PROXIES_FILE: Path = BASE_DIR / "working_proxies.txt"
    
    LOG_LEVEL: str = "INFO"
    MAX_CONCURRENT_DOWNLOADS: int = 3
    DOWNLOAD_TIMEOUT: int = 120

    # --- ВАЛИДАТОРЫ ---

    @field_validator("COBALT_INSTANCES", "PIPED_INSTANCES", mode="before")
    @classmethod
    def _parse_instances(cls, v: Any, info: ValidationInfo) -> List[str]:
        # RESURRECTION LIST 2026
        defaults = {
            "COBALT_INSTANCES": [
                "https://api.cobalt.tools",       # Official
                "https://cobalt.awery.net",       # Reliable Mirror
                "https://cobalt.root.sx",         # Reliable Mirror
                "https://cobalt.lanex.dev",       # Reliable Mirror
                "https://cobalt.154.53.53.153.sslip.io" # Direct IP Mirror
            ],
            "PIPED_INSTANCES": [
                "https://pipedapi.kavin.rocks",
                "https://api.piped.otter.sh",
                "https://pipedapi.drgns.space",
                "https://api.piped.projectsegfau.lt",
                "https://pipedapi.adminforge.de",
                "https://pipedapi.ducks.party",
                "https://api.piped.yt",
                "https://pipedapi.system41.space",
                "https://pipedapi.leptons.xyz"
            ]
        }
        
        field_name = info.field_name
        default_list = defaults.get(field_name, [])

        if v is None: return default_list
        if isinstance(v, str):
            v = v.strip()
            if not v: return default_list
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list): return parsed
            except json.JSONDecodeError: pass
            return [i.strip() for i in v.split(",") if i.strip()]
        if isinstance(v, list): return v if v else default_list
        return default_list

    @field_validator("ADMIN_ID_LIST", mode="before")
    @classmethod
    def _assemble_admin_ids(cls, v: Any, info: ValidationInfo) -> List[int]:
        admin_ids_str = info.data.get("ADMIN_IDS", "")
        if not admin_ids_str: return []
        try: return [int(i.strip()) for i in str(admin_ids_str).split(",") if i.strip()]
        except ValueError: return []

@lru_cache()
def get_settings() -> Settings:
    return Settings()