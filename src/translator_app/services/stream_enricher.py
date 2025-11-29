import httpx
import asyncio
import time
from typing import List, Optional, Dict
from src.translator_app.settings import settings
from src.translator_app.logger import logger
from src.translator_app.constants import (
    BULGARIAN_FLAG,
    ENRICH_LEVEL_DISABLED,
    ENRICH_LEVEL_SCRAPER_ONLY,
    ENRICH_LEVEL_FULL_PROBE
)
from src.translator_app import stream_probe

async def _rd_unrestrict(client: httpx.AsyncClient, link: str) -> Optional[str]:
    try:
        resp = await client.post(
            "https://api.real-debrid.com/rest/1.0/unrestrict/link",
            data={"link": link},
            headers={"Authorization": f"Bearer {settings.effective_rd_token}"},
            timeout=settings.request_timeout,
        )
        if resp.status_code >= 400:
            return None
        data = resp.json()
        return data.get("download")
    except Exception:
        return None


async def _rd_poll_info(client: httpx.AsyncClient, torrent_id: str) -> Optional[Dict]:
    try:
        resp = await client.get(
            f"https://api.real-debrid.com/rest/1.0/torrents/info/{torrent_id}",
            headers={"Authorization": f"Bearer {settings.effective_rd_token}"},
            timeout=settings.request_timeout,
        )
        if resp.status_code >= 400:
            return None
        return resp.json()
    except Exception:
        return None


async def _rd_select_file(client: httpx.AsyncClient, torrent_id: str, file_idx: int) -> None:
    try:
        await client.post(
            f"https://api.real-debrid.com/rest/1.0/torrents/selectFiles/{torrent_id}",
            data={"files": str(file_idx)},
            headers={"Authorization": f"Bearer {settings.effective_rd_token}"},
            timeout=settings.request_timeout,
        )
    except Exception:
        return


async def _resolve_with_rd(info_hash: str, file_idx: Optional[int]) -> Optional[str]:
    if not settings.effective_rd_token:
        return None
    magnet = f"magnet:?xt=urn:btih:{info_hash}"
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            # Add magnet
            add_resp = await client.post(
                "https://api.real-debrid.com/rest/1.0/torrents/addMagnet",
                data={"magnet": magnet},
                headers={"Authorization": f"Bearer {settings.effective_rd_token}"},
            )
            if add_resp.status_code >= 400:
                return None
            torrent_id = add_resp.json().get("id")
            if not torrent_id:
                return None

            # Select desired file if provided
            if file_idx is not None:
                await _rd_select_file(client, torrent_id, file_idx)

            # Poll for availability and links
            deadline = time.time() + settings.rd_poll_max_seconds
            links: List[str] = []
            while time.time() < deadline:
                info = await _rd_poll_info(client, torrent_id)
                if not info:
                    await asyncio.sleep(settings.rd_poll_interval)
                    continue
                links = info.get("links") or []
                status = info.get("status") or ""
                if links:
                    break
                if status in {"magnet_error", "error", "virus", "dead"}:
                    return None
                await asyncio.sleep(settings.rd_poll_interval)

            if not links:
                return None

            # Unrestrict first link
            direct = await _rd_unrestrict(client, links[0])
            return direct or links[0]
    except Exception:
        return None
    return None

async def enrich_streams_with_subtitles(
    streams: List[dict],
    media_type: Optional[str] = None,
    item_id: Optional[str] = None,
    request_base: Optional[str] = None,
    enrich_level: Optional[int] = None,
) -> List[dict]:
    """
    Enrich streams with subtitle information.
    
    Args:
        streams: List of stream objects to enrich
        media_type: Type of media (movie/series)
        item_id: IMDb ID or other identifier
        request_base: Base URL for BG subtitle scraper
        enrich_level: 0=disabled, 1=scraper only (fast), 2=full probing (slow)
    
    Returns:
        Enriched and sorted streams
    """
    if not streams:
        return streams
    
    # Use default if not specified
    if enrich_level is None:
        enrich_level = settings.default_stream_enrich_level
    
    # Level 0: No enrichment, return as-is
    if enrich_level == ENRICH_LEVEL_DISABLED:
        logger.info(f"Stream enrichment disabled (level={ENRICH_LEVEL_DISABLED}), returning {len(streams)} streams as-is")
        return streams

    def _subtitle_langs_has_bg(raw_langs) -> bool:
        langs: List[str] = []
        if isinstance(raw_langs, str):
            langs.extend([lang.strip().lower() for lang in raw_langs.split(",") if lang])
        elif isinstance(raw_langs, list):
            langs.extend([str(lang).strip().lower() for lang in raw_langs if lang])
        return any(l.startswith("bg") or l.startswith("bul") for l in langs)

    def _mark_bg_content(stream: dict) -> None:
        """Mark Bulgarian subtitles AND audio based on metadata and probe results."""
        
        # 1. Check for BG Subtitles (Embedded)
        tracks = stream.get("embeddedSubtitles") or []
        bg_in_embedded = False
        
        for track in tracks:
            lang = str((track or {}).get("lang") or "").strip().lower()
            title = str((track or {}).get("title") or "").strip().lower()
            
            if lang.startswith("bg") or lang.startswith("bul"):
                bg_in_embedded = True
                break
            if "bulgarian" in title:
                bg_in_embedded = True
                break
        
        # 2. Check for BG Audio (Filename & Probe)
        bg_audio_found = False
        
        # Check filename regex
        name = str(stream.get("name") or "")
        title = str(stream.get("title") or "")
        filename = str(stream.get("filename") or "")
        combined_text = (name + " " + title + " " + filename).lower()
        
        # Normalize separators to spaces for better keyword matching
        import re
        combined_text = re.sub(r'[._\-]+', ' ', combined_text)
        
        audio_keywords = [
            "bg audio", "bgaudio", "bg-audio",
            "bg dub", "bgdub", "bg-dub",
            "бг аудио", "бг дублаж",
            "bulgarian audio", "bulgarian dub"
        ]
        
        if any(kw in combined_text for kw in audio_keywords):
            bg_audio_found = True
            
        # Check probe results (if available)
        if stream.get("audio_langs"):
            audio_langs = stream.get("audio_langs") or []
            if any(l.startswith("bg") or l.startswith("bul") for l in audio_langs):
                bg_audio_found = True

        # Apply flags
        tags = stream.get("visualTags") or []
        
        # Subtitles Flagging
        if bg_in_embedded:
            stream["subs_bg"] = True
            if "bg-subs" not in tags:
                tags.append("bg-subs")
            if "bg-embedded" not in tags:
                tags.append("bg-embedded")
        
        # Audio Flagging
        if bg_audio_found:
            stream["audio_bg"] = True
            if "bg-audio" not in tags:
                tags.append("bg-audio")
                
        stream["visualTags"] = tags

        # Inject Visual Indicators
        # 🇧🇬 = Subtitles
        # 🔊 = Audio
        # 🇧🇬🔊 = Both
        
        flags = []
        if bg_in_embedded:
            flags.append(BULGARIAN_FLAG)
        if bg_audio_found:
            flags.append("🔊")
            
        if not flags:
            # Cleanup if re-processing
            try:
                clean_name = name.replace(BULGARIAN_FLAG, "").replace("🔊", "").replace("💿", "").strip()
                stream["name"] = clean_name
            except Exception:
                pass
            return

        flag_str = " ".join(flags)
        
        try:
            # Avoid duplication
            current_name = str(stream.get("name") or "")
            
            # Clean up existing flags first to ensure clean state
            clean_name = current_name.replace(BULGARIAN_FLAG, "").replace("🔊", "").replace("💿", "").strip()
            
            # Re-inject flags at the start
            stream["name"] = f"{flag_str} {clean_name}".strip()
        except Exception:
            pass
            
        try:
            desc = str(stream.get("description") or "")
            if flag_str not in desc:
                stream["description"] = f"{desc} ⚑ {flag_str}".strip()
        except Exception:
            pass

    # Level 2: Full enrichment with video probing and RealDebrid
    if enrich_level >= ENRICH_LEVEL_FULL_PROBE:
        logger.info(f"Stream enrichment level 2: Full probing for {len(streams)} streams")
        
        # Parallelize RealDebrid resolution for magnets
        async def _resolve_stream_magnet(stream: dict) -> None:
            """Resolve a single stream's magnet to direct URL via RealDebrid."""
            if stream.get("url"):
                return
            info_hash = stream.get("infoHash") or stream.get("info_hash")
            if not info_hash:
                return
            try:
                file_idx = None
                raw_idx = stream.get("fileIdx")
                if raw_idx is not None:
                    try:
                        file_idx = int(raw_idx)
                    except Exception:
                        file_idx = None
                resolved = await _resolve_with_rd(info_hash, file_idx)
                if resolved:
                    stream["url"] = resolved
                    stream.setdefault("behaviorHints", {})
                    stream["behaviorHints"]["rdResolved"] = True
            except Exception:
                pass
        
        # Process all magnet resolutions in parallel
        magnet_streams = [s for s in streams if not s.get("url") and (s.get("infoHash") or s.get("info_hash"))]
        if magnet_streams:
            await asyncio.gather(*[_resolve_stream_magnet(s) for s in magnet_streams], return_exceptions=True)

        # Honor any subtitle metadata already present (e.g., upstream provided subtitleLangs/embeddedSubtitles)
        for stream in streams:
            _mark_bg_content(stream)

        # Smart stream selection: Prioritize high-quality streams for probing
        def _stream_quality_score(stream: dict) -> int:
            """Score stream by quality to prioritize better streams for probing."""
            name = str(stream.get("name") or "").lower()
            score = 0
            
            # Resolution priority
            if "2160p" in name or "4k" in name:
                score += 40
            elif "1440p" in name:
                score += 30
            elif "1080p" in name:
                score += 20
            elif "720p" in name:
                score += 10
                
            # Quality tags
            if "remux" in name or "bluray" in name:
                score += 15
            elif "web-dl" in name or "webdl" in name:
                score += 10
            elif "webrip" in name:
                score += 5
                
            # Prefer torrents over magnets (already have URL)
            if stream.get("url"):
                score += 25
                
            return score
        
        # Sort streams by quality score (descending) and select top N for probing
        probeable_streams = [s for s in streams if s.get("url") and s["url"].lower().startswith(("http://", "https://"))]
        probeable_streams.sort(key=_stream_quality_score, reverse=True)
        
        tasks = []
        targets = probeable_streams[:settings.stream_subs_max_streams]
        
        for stream in targets:
            tasks.append(asyncio.create_task(stream_probe.probe(stream["url"])))

        if tasks:
            results = await asyncio.gather(*tasks)
            for stream, meta in zip(targets, results):
                if not meta:
                    continue
                
                # Process Subtitles
                langs = [lang for lang in (meta.get("langs") or []) if lang]
                if langs:
                    stream["subtitleLangs"] = ",".join(langs)
                    for lang in langs:
                        stream[f"subs_{lang}"] = True
                
                tracks = meta.get("tracks") or []
                if tracks:
                    stream["embeddedSubtitles"] = tracks
                    
                # Process Audio
                audio_langs = [lang for lang in (meta.get("audio_langs") or []) if lang]
                if audio_langs:
                    stream["audio_langs"] = audio_langs
                    
                # Re-apply marker after probe results
                _mark_bg_content(stream)
    else:
        # Level 1: Only check upstream metadata, no probing
        logger.info(f"Stream enrichment level {ENRICH_LEVEL_SCRAPER_ONLY}: Scraper check only (no video probing)")
        for stream in streams:
            _mark_bg_content(stream)

    # Scraper check removed to comply with strict "Embedded ONLY" flagging requirement.
    # External subtitles will not trigger any flags or indicators.

    # Prioritize streams: 
    # 1) BG Audio (Rare & High Value)
    # 2) BG Embedded Subs
    # 3) BG Found (but not embedded)
    # 4) Everything else
    def _priority(stream: dict) -> int:
        tags = stream.get("visualTags") or []
        has_bg_audio = "bg-audio" in tags
        has_bg_embedded = "bg-embedded" in tags
        
        # Check for any indication of BG subs (scraped, metadata, or embedded list)
        has_bg_subs = bool(
            stream.get("subs_bg")
            or ("bg-subs" in tags)
            or _subtitle_langs_has_bg(stream.get("subtitleLangs"))
        )

        if has_bg_audio:
            return 0  # 1. BG Audio (Top Priority)
        if has_bg_embedded:
            return 1  # 2. BG Embedded Subs
        if has_bg_subs:
            return 2  # 3. BG Found (but not embedded)
        return 3      # 4. Everything else

    indexed_sorted = sorted(enumerate(streams), key=lambda pair: (_priority(pair[1]), pair[0]))
    return [stream for _, stream in indexed_sorted]
