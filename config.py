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
    
    # --- API Pools (CRITICAL FIX) ---
    # Используем Union, чтобы Pydantic не падал при чтении пустой строки из ENV
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
    
    LOG_LEVEL: str = "INFO"
    MAX_CONCURRENT_DOWNLOADS: int = 3
    DOWNLOAD_TIMEOUT: int = 60

    # --- ВАЛИДАТОРЫ ---

    @field_validator("COBALT_INSTANCES", "PIPED_INSTANCES", mode="before")
    @classmethod
    def _parse_instances(cls, v: Any, info: ValidationInfo) -> List[str]:
        """
        Безопасный парсинг. Возвращает список URL.
        """
        # Хардкод дефолтных списков (Спасательный круг)
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

        # 1. Если пришел None
        if v is None:
            return default_list
            
        # 2. Если пришла строка (пустая или JSON или CSV)
        if isinstance(v, str):
            v = v.strip()
            if not v: # Пустая строка -> дефолт
                return default_list
            
            try:
                # Попытка парсинга JSON
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass
            
            # Попытка парсинга через запятую
            return [i.strip() for i in v.split(",") if i.strip()]

        # 3. Если уже список
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