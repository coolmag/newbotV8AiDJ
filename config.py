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
    
    # --- Mandatory Settings (Переменные окружения) ---
    BOT_TOKEN: str 
    WEBHOOK_URL: str 
    BASE_URL: str = ""
    ADMIN_IDS: str = ""
    COOKIES_CONTENT: str = ""
    PROXY_URL: Optional[str] = None
    BASE_DIR: Path = Path(__file__).resolve().parent
    DOWNLOADS_DIR: Path = BASE_DIR / "downloads"
    TEMP_AUDIO_DIR: Path = BASE_DIR / "temp_audio"
    CACHE_DB_PATH: Path = BASE_DIR / "cache.db"
    COOKIES_FILE: Path = BASE_DIR / "cookies.txt"
    LOG_LEVEL: str = "INFO"
    MAX_FILE_SIZE_MB: int = 49
    RADIO_MIN_DURATION_S: int = 60    
    RADIO_MAX_DURATION_S: int = 900   
    GENRE_SEARCH_MIN_DURATION_S: int = 120   
    GENRE_SEARCH_MAX_DURATION_S: int = 600 
    ADMIN_ID_LIST: List[int] = []
    
    # Настройки очистки (новые, чтобы не забить диск)
    CLEANUP_INTERVAL_SECONDS: int = 3600  # Раз в час
    FILE_MAX_AGE_SECONDS: int = 86400     # 24 часа

    @field_validator("ADMIN_ID_LIST", mode="before")
    @classmethod
    def _assemble_admin_ids(cls, v, info) -> List[int]:
        admin_ids_str = info.data.get("ADMIN_IDS", "")
        if not admin_ids_str: return []
        try:
            return [int(i.strip()) for i in admin_ids_str.split(",") if i.strip()]
        except ValueError as e:
            print(f"⚠️ Ошибка парсинга ADMIN_IDS: {e}")
            return []

@lru_cache()
def get_settings() -> Settings:
    return Settings()
