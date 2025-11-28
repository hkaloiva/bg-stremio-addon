from pydantic_settings import BaseSettings
from typing import Optional, List
import os

class Settings(BaseSettings):
    translator_version: str = "v1.0.9-performance"
    default_language: str = "bg-BG"
    force_prefix: bool = False
    force_meta: bool = False
    use_tmdb_id_meta: bool = True
    use_tmdb_addon: bool = False
    translate_catalog_name: bool = False
    request_timeout: int = 120
    compatibility_id: List[str] = ['tt', 'kitsu', 'mal']
    enable_anime: bool = False
    subs_proxy_base: str = "https://stremio-community-subtitles.top"
    
    # Stream enrichment settings
    # 0 = disabled (fastest, no subtitle detection)
    # 1 = scraper only (fast, 1-2s, checks BG subtitle availability)
    # 2 = full enrichment (optimized, 10-15s, probes top 2 video files + RealDebrid)
    default_stream_enrich_level: int = 2
    stream_subs_max_streams: int = 5  # Probe top 5 streams for better coverage
    
    rd_token: Optional[str] = None
    realdebrid_token: Optional[str] = None
    rd_poll_max_seconds: int = 10  # Faster timeout for RealDebrid
    rd_poll_interval: float = 1.5  # Faster polling
    admin_password: Optional[str] = None
    tr_server: str = 'https://ca6771aaa821-toast-ratings.baby-beamup.club'
    testing: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def effective_rd_token(self) -> Optional[str]:
        return self.rd_token or self.realdebrid_token or "EIWFM2CK35TX3MTMFPV6D7DNJIXQFIZDWDCHD5ZFL5A3ELPKBR5A"

settings = Settings()
