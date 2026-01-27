from pathlib import Path
from typing import List, Any, Optional
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
    
    # API Pools (с защитой от сбоев парсинга)
    COBALT_INSTANCES: List[str] = []
    PIPED_INSTANCES: List[str] = []

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

    # --- ВАЛИДАТОРЫ ---

    @field_validator("COBALT_INSTANCES", "PIPED_INSTANCES", mode="before")
    @classmethod
    def _parse_instances(cls, v: Any, info: ValidationInfo) -> List[str]:
        """
        Безопасный парсинг списков инстансов.
        Если в ENV пусто или мусор - возвращает жестко заданные дефолты.
        """
        # Жестко заданные резервные списки (DEFAULTS)
        defaults = {
            "COBALT_INSTANCES": [
                "https://cobalt.api.sc",
                "https://co.wuk.sh",
                "https://api.cobalt.7o7.tech",
                "https://cobalt.tools",
                "https://cobalt.xy24.eu.org",
            ],
            "PIPED_INSTANCES": [
                "https://pipedapi.kavin.rocks",
                "https://api.piped.otter.sh",
                "https://pipedapi.drgns.space",
                "https://api.piped.yt",
                "https://pipedapi.nosebs.ru"
            ]
        }
        
        field_name = info.field_name
        default_list = defaults.get(field_name, [])

        # Если значение пришло пустым или None
        if v is None:
            return default_list
        
        if isinstance(v, str):
            v = v.strip()
            if not v: # Пустая строка
                return default_list
            try:
                # Пробуем как JSON (например '["url1", "url2"]')
                return json.loads(v)
            except json.JSONDecodeError:
                # Пробуем как CSV (url1,url2)
                return [i.strip() for i in v.split(",") if i.strip()]
        
        if isinstance(v, list):
            return v if v else default_list
            
        return default_list

    @field_validator("ADMIN_ID_LIST", mode="before")
    @classmethod
    def _assemble_admin_ids(cls, v: Any, info: ValidationInfo) -> List[int]:
        admin_ids_str = info.data.get("ADMIN_IDS", "")
        if not admin_ids_str: 
            return []
        try:
            return [int(i.strip()) for i in str(admin_ids_str).split(",") if i.strip()]
        except ValueError: 
            return []

@lru_cache()
def get_settings() -> Settings:
    return Settings()