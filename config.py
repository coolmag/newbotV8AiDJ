from pathlib import Path
from typing import List, Dict, Any, Optional
from functools import lru_cache
import os

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator

# ===========================
# ГЛОБАЛЬНЫЙ КАТАЛОГ ЖАНРОВ
# ===========================
MUSIC_CATALOG = {
    # =========================
    # 🔥 ТОП / БЫСТРЫЙ СТАРТ
    # =========================
    "🔥 Топ-чарты": {
        "Global Top 50": "top 50 global hits official",
        "Viral / TikTok": "tiktok viral hits music",
        "Fresh 2024–2025": "new music hits 2024 2025"
    },

    # =========================
    # 🎸 ROCK
    # =========================
    "🎸 Rock": {
        "Classic Rock": {
            "All": "classic rock greatest hits",
            "1960s": "60s classic rock",
            "1970s": "70s classic rock led zeppelin pink floyd",
            "1980s": "80s classic rock"
        },
        "Alternative Rock": {
            "All": "alternative rock mix",
            "1990s": "90s alternative rock nirvana pearl jam",
            "2000s": "2000s alternative rock linkin park muse",
            "2010s": "2010s alternative rock"
        },
        "Indie Rock": {
            "All": "indie rock mix",
            "2000s": "2000s indie rock the strokes",
            "2010s": "2010s indie rock"
        },
        "Hard Rock": {
            "All": "hard rock greatest hits",
            "1980s": "80s hard rock guns n roses acdc",
            "1990s": "90s hard rock"
        },
        "Metal": {
            "Classic Metal": "classic heavy metal iron maiden judas priest",
            "Nu Metal": "nu metal linkin park limp bizkit",
            "Modern Metal": "modern metal core"
        },
        "Punk Rock": {
            "Classic Punk": "classic punk ramones sex pistols",
            "Pop Punk": "pop punk blink 182 green day"
        }
    },

    # =========================
    # 🎷 JAZZ / BLUES / SOUL
    # =========================
    "🎷 Jazz & Blues": {
        "Classic Jazz": {
            "All": "classic jazz greatest hits",
            "1940s–50s": "bebop jazz miles davis charlie parker",
            "1960s": "modal jazz john coltrane"
        },
        "Smooth Jazz": {
            "All": "smooth jazz chill",
            "1990s": "90s smooth jazz",
            "2000s": "2000s smooth jazz"
        },
        "Blues": {
            "Delta Blues": "delta blues classics",
            "Blues Rock": "blues rock guitar legends",
            "Modern Blues": "modern blues rock"
        },
        "Soul & Funk": {
            "Classic Soul": "classic soul marvin gaye otis reddin",
            "Funk": "70s funk classics"
        }
    },

    # =========================
    # 🎤 HIP-HOP / R&B
    # =========================
    "🎤 Hip-Hop & R&B": {
        "Old School": {
            "1980s": "80s hip hop old school",
            "1990s": "90s hip hop golden age"
        },
        "2000s Era": {
            "All": "2000s hip hop classics",
            "East Coast": "2000s east coast hip hop",
            "West Coast": "2000s west coast hip hop"
        },
        "Modern Hip-Hop": {
            "Trap": "modern trap hip hop",
            "Drill": "drill hip hop",
            "Cloud": "cloud rap"
        },
        "R&B": {
            "1990s": "90s rnb classics",
            "2000s": "2000s rnb hits",
            "Neo Soul": "neo soul rnb"
        }
    },

    # =========================
    # 🎧 ELECTRONIC
    # =========================
    "🎧 Electronic": {
        "House": {
            "All": "house music mix",
            "1990s": "90s house music",
            "2000s": "2000s house music",
            "Deep House": "deep house"
        },
        "Techno": {
            "All": "techno club mix",
            "Minimal": "minimal techno",
            "Industrial": "industrial techno"
        },
        "Trance": {
            "Classic": "classic trance anthems",
            "Uplifting": "uplifting trance"
        },
        "Drum & Bass": {
            "Liquid": "liquid drum and bass",
            "Neurofunk": "neurofunk dnb"
        },
        "Synth / Retro": {
            "Synthwave": "synthwave retrowave",
            "Retrowave": "retro wave 80s style"
        }
    },

    # =========================
    # ✨ POP
    # =========================
    "✨ Pop": {
        "1980s": "80s pop hits michael jackson madonna",
        "1990s": {
            "All": "90s pop hits",
            "Eurodance": "90s eurodance hits",
            "US / UK": "90s pop usa uk"
        },
        "2000s": {
            "All": "2000s pop hits",
            "MTV Era": "2000s mtv pop hits"
        },
        "Modern Pop": "modern pop hits"
    },

    # =========================
    # 🇷🇺 RUSSIAN MUSIC
    # =========================
    "🇷🇺 Russian Music": {
        "Soviet & Retro": {
            "Golden Hits": "лучшие песни ссср 70 80",
            "Movies": "песни из советских фильмов",
            "VIA": "виа ссср песняры самоцветы"
        },
        "Russian Rock": {
            "Legends": "русский рок кино би 2 сплин",
            "Modern": "современный русский рок",
            "Punk": "король и шут сектор газа"
        },
        "Russian Pop": {
            "1990s": "русская дискотека 90",
            "2000s": "русские хиты 2000",
            "Modern": "русские поп хиты 2024"
        },
        "Russian Rap": {
            "Old School": "русский рэп 2000 баста гуф",
            "New School": "русский рэп новинки",
            "Chill / Lyric": "лирика русский рэп"
        }
    },

    # =========================
    # 🎯 MOODS / USE CASES
    # =========================
    "🎯 Mood & Activity": {
        "Work / Focus": "deep focus music for work",
        "Gym": "gym workout motivation music",
        "Chill / Relax": "chill lofi beats",
        "Party": "party dance hits",
        "Night Drive": "night drive music",
        "Sleep / Ambient": "ambient music for sleep",
        "Classical": {
            "Baroque": "baroque classical music",
            "Romantic": "romantic era classical music",
            "Modern": "modern classical music"
        }
    }
}

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
