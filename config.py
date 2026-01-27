from pathlib import Path
from typing import List, Any, Optional
from functools import lru_cache
import logging
import os

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
    
    # --- YouTube Authentication ---
    # В 2026 году Cookies и PO_TOKEN критичны для прямой загрузки
    COOKIES_CONTENT: str = ""
    PO_TOKEN: Optional[str] = None 
    VISITOR_DATA: Optional[str] = None
    
    # --- Proxy / External APIs ---
    PROXY_URL: Optional[str] = None
    
    # Список инстансов Cobalt (Лучшее решение для 2025/2026)
    # Это публичные инстансы, можно поднять свой на Railway
    COBALT_INSTANCES: List[str] = [
        "https://cobalt.api.sc",
        "https://co.wuk.sh",
        "https://api.cobalt.7o7.tech",
        "https://cobalt.tools"
    ]
    
    # Список инстансов Piped (Резерв)
    PIPED_INSTANCES: List[str] = [
        "https://pipedapi.kavin.rocks",
        "https://api.piped.otter.sh",
        "https://pipedapi.drgns.space"
    ]

    GEMINI_API_KEY: Optional[str] = None
    VK_LOGIN: Optional[str] = None
    VK_PASSWORD: Optional[str] = None
    
    ADMIN_ID_LIST: List[int] = []
    
    BASE_DIR: Path = Path(__file__).resolve().parent
    DOWNLOADS_DIR: Path = BASE_DIR / "downloads"
    TEMP_AUDIO_DIR: Path = BASE_DIR / "temp_audio"
    CACHE_DB_PATH: Path = BASE_DIR / "cache.db"
    COOKIES_FILE: Path = BASE_DIR / "cookies.txt"
    
    LOG_LEVEL: str = "INFO"
    MAX_CONCURRENT_DOWNLOADS: int = 3
    DOWNLOAD_TIMEOUT: int = 60

    @field_validator("ADMIN_ID_LIST", mode="before")
    @classmethod
    def _assemble_admin_ids(cls, v: Any, info: ValidationInfo) -> List[int]:
        admin_ids_str = info.data.get("ADMIN_IDS", "")
        if not admin_ids_str: return []
        try:
            return [int(i.strip()) for i in str(admin_ids_str).split(",") if i.strip()]
        except ValueError: return []

@lru_cache()
def get_settings() -> Settings:
    return Settings()