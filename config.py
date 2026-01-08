from pathlib import Path
from typing import List, Dict, Any, Optional
from functools import lru_cache
import os

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )
    
    # --- Mandatory Settings ---
    BOT_TOKEN: str 
    WEBHOOK_URL: str 
    BASE_URL: str = ""
    ADMIN_IDS: str = ""
    COOKIES_CONTENT: str = ""
    PROXY_URL: Optional[str] = None
    
    # --- Paths ---
    BASE_DIR: Path = Path(__file__).resolve().parent
    DOWNLOADS_DIR: Path = BASE_DIR / "downloads"
    TEMP_AUDIO_DIR: Path = BASE_DIR / "temp_audio"
    CACHE_DB_PATH: Path = BASE_DIR / "cache.db"
    COOKIES_FILE: Path = BASE_DIR / "cookies.txt"
    
    # --- Logging ---
    LOG_LEVEL: str = "INFO"
    
    # --- Scaling & Limits (ВОТ ЧЕГО НЕ ХВАТАЛО) ---
    MAX_CONCURRENT_DOWNLOADS: int = 3
    DOWNLOAD_TIMEOUT: int = 45
    
    # --- Cleanup ---
    CLEANUP_INTERVAL_SECONDS: int = 600  
    FILE_MAX_AGE_SECONDS: int = 1800     

    @field_validator("ADMIN_ID_LIST", mode="before")
    @classmethod
    def _assemble_admin_ids(cls, v, info) -> List[int]:
        return []

 @lru_cache()
def get_settings() -> Settings:
    return Settings()