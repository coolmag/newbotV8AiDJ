from pathlib import Path
from typing import List, Dict, Any, Optional
from functools import lru_cache
import os
import logging # Added for diagnostics

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, ValidationInfo

# Added for diagnostics
logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )
    
    BOT_TOKEN: str 
    WEBHOOK_URL: str 
    BASE_URL: str = ""
    ADMIN_IDS: str = ""
    COOKIES_CONTENT: str = ""
    PROXY_URL: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    
    # --- VK Music Engine (Railway-friendly) ---
    VK_LOGIN: Optional[str] = None
    VK_PASSWORD: Optional[str] = None
    
    # --- Явное объявление полей ---
    ADMIN_ID_LIST: List[int] = []
    
    BASE_DIR: Path = Path(__file__).resolve().parent
    DOWNLOADS_DIR: Path = BASE_DIR / "downloads"
    TEMP_AUDIO_DIR: Path = BASE_DIR / "temp_audio"
    CACHE_DB_PATH: Path = BASE_DIR / "cache.db"
    COOKIES_FILE: Path = BASE_DIR / "cookies.txt"
    
    LOG_LEVEL: str = "INFO"
    
    # --- Настройки нагрузки ---
    MAX_CONCURRENT_DOWNLOADS: int = 3
    DOWNLOAD_TIMEOUT: int = 45
    CLEANUP_INTERVAL_SECONDS: int = 600  
    FILE_MAX_AGE_SECONDS: int = 1800     

    @field_validator("ADMIN_ID_LIST", mode="before")
    @classmethod
    def _assemble_admin_ids(cls, v: Any, info: ValidationInfo) -> List[int]:
        admin_ids_str = info.data.get("ADMIN_IDS", "")
        logger.info(f"⚙️ ADMIN_IDS from env: '{admin_ids_str}'")

        if not admin_ids_str:
            logger.warning("ADMIN_IDS is empty. No admins configured.")
            return []
        try:
            id_list = [int(i.strip()) for i in str(admin_ids_str).split(",") if i.strip()]
            logger.info(f"✅ Parsed admin IDs: {id_list}")
            return id_list
        except ValueError as e:
            logger.error(f"❌ Failed to parse ADMIN_IDS. Check for non-numeric values. Error: {e}")
            return []

@lru_cache()
def get_settings() -> Settings:
    return Settings()