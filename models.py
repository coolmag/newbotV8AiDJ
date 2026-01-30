from dataclasses import dataclass
from typing import Optional
from pathlib import Path

@dataclass
class TrackInfo:
    identifier: str
    title: str
    duration: int
    # 👇 Оставляем то поле, которое у тебя реально есть (uploader)
    uploader: str = "Unknown Artist" 
    thumbnail_url: Optional[str] = None
    source: str = "youtube"

    # 👇 МАГИЯ: Делаем алиас. Если код просит .artist, отдаем .uploader
    @property
    def artist(self) -> str:
        return self.uploader
        
    @classmethod
    def from_yt_info(cls, info: dict):
        return cls(
            identifier=info.get('id', ''),
            title=info.get('title', 'Unknown'),
            uploader=info.get('uploader', info.get('artist', 'Unknown')),
            duration=int(info.get('duration', 0)),
            thumbnail_url=info.get('thumbnail')
        )

@dataclass
class DownloadResult:
    success: bool
    file_path: Optional[Path] = None
    file_id: Optional[str] = None
    track_info: Optional[TrackInfo] = None
    error_message: Optional[str] = None