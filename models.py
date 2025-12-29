from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Any, Dict


class Source(Enum):
    YOUTUBE = "youtube"
    SPOTIFY = "spotify"
    SOUNDCLOUD = "soundcloud"


@dataclass
class TrackInfo:
    identifier: str
    title: str
    artist: str
    duration: int
    source: Source = Source.YOUTUBE
    thumbnail_url: Optional[str] = None
    
    @classmethod
    def from_yt_info(cls, info: Dict[str, Any]) -> Optional["TrackInfo"]:
        if not info:
            return None
        
        video_id = info.get('id')
        if not video_id:
            url = info.get('url', '')
            if 'watch?v=' in url:
                video_id = url.split('watch?v=')[-1].split('&')[0]
            elif 'youtu.be/' in url:
                video_id = url.split('youtu.be/')[-1].split('?')[0]
        
        if not video_id:
            return None
        
        title = info.get('title', 'Unknown')
        artist = (
            info.get('artist') or 
            info.get('creator') or 
            info.get('uploader') or 
            info.get('channel') or 
            'Unknown'
        )
        duration = info.get('duration') or 0
        thumbnail = info.get('thumbnail')
        
        # Пытаемся разбить "Artist - Title" если артист неизвестен
        if " - " in title and artist in ["Unknown", "Various Artists"]:
            try:
                parts = title.split(" - ", 1)
                artist, title = parts[0].strip(), parts[1].strip()
            except Exception:
                pass
        
        return cls(
            identifier=video_id,
            title=title,
            artist=artist,
            duration=int(duration),
            source=Source.YOUTUBE,
            thumbnail_url=thumbnail
        )


@dataclass
class DownloadResult:
    success: bool
    file_path: Optional[Path] = None
    file_id: Optional[str] = None
    track_info: Optional[TrackInfo] = None
    error_message: Optional[str] = None


@dataclass
class SearchResult:
    query: str
    tracks: list
    total: int = 0
    page: int = 1
    has_more: bool = False


@dataclass 
class RadioState:
    chat_id: int
    genre: str
    is_playing: bool = False
    current_track: Optional[TrackInfo] = None
    queue_size: int = 0
