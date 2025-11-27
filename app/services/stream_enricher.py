import httpx
import asyncio
import time
from typing import List, Optional, Dict
from app.settings import settings
from app.logger import logger
import stream_probe

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
    if enrich_level == 0:
        logger.info(f"Stream enrichment disabled (level=0), returning {len(streams)} streams as-is")
        return streams

    def _subtitle_langs_has_bg(raw_langs) -> bool:
        langs: List[str] = []
        if isinstance(raw_langs, str):
            langs.extend([lang.strip().lower() for lang in raw_langs.split(",") if lang])
        elif isinstance(raw_langs, list):
            langs.extend([str(lang).strip().lower() for lang in raw_langs if lang])
        return any(l.startswith("bg") or l.startswith("bul") for l in langs)

    def _mark_bg_subs(stream: dict) -> None:
        """Mark Bulgarian subtitles based on any known subtitle metadata."""
        raw_langs = stream.get("subtitleLangs")
        langs: List[str] = []
        if isinstance(raw_langs, str):
            langs.extend([lang.strip().lower() for lang in raw_langs.split(",") if lang])
        elif isinstance(raw_langs, list):
            langs.extend([str(lang).strip().lower() for lang in raw_langs if lang])

        tracks = stream.get("embeddedSubtitles") or []
        bg_in_embedded = False
        for track in tracks:
            lang = str((track or {}).get("lang") or "").strip().lower()
            if lang:
                langs.append(lang)
            if lang.startswith("bg") or lang.startswith("bul"):
                bg_in_embedded = True

        has_bg = any(l.startswith("bg") or l.startswith("bul") for l in langs)
        if not has_bg:
            return

        stream["subs_bg"] = True
        tags = stream.get("visualTags") or []
        if "bg-subs" not in tags:
            tags.append("bg-subs")
        if bg_in_embedded and "bg-embedded" not in tags:
            tags.append("bg-embedded")
        stream["visualTags"] = tags

        # Inject visual hints into name/description so upstream formatting limitations are bypassed.
        flag = "🇧🇬📀" if bg_in_embedded else "🇧🇬"
        try:
            name = str(stream.get("name") or "")
            if flag not in name:
                stream["name"] = f"{flag} {name}".strip()
        except Exception:
            pass
        try:
            desc = str(stream.get("description") or "")
            if flag not in desc:
                stream["description"] = f"{desc} ⚑ {flag}".strip()
        except Exception:
            pass

    # Level 2: Full enrichment with video probing and RealDebrid
    if enrich_level >= 2:
        logger.info(f"Stream enrichment level 2: Full probing for {len(streams)} streams")
        
        # Attempt to resolve magnet-only streams via Real-Debrid to obtain a direct URL for probing
        for stream in streams:
            if stream.get("url"):
                continue
            info_hash = stream.get("infoHash") or stream.get("info_hash")
            if not info_hash:
                continue
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
                    # Mark as resolved for downstream awareness
                    stream.setdefault("behaviorHints", {})
                    stream["behaviorHints"]["rdResolved"] = True
            except Exception:
                continue

        # Honor any subtitle metadata already present (e.g., upstream provided subtitleLangs/embeddedSubtitles)
        for stream in streams:
            _mark_bg_subs(stream)

        tasks = []
        targets = []
        for stream in streams:
            url = stream.get("url")
            if not url or not url.lower().startswith(("http://", "https://")):
                continue
            if len(targets) >= settings.stream_subs_max_streams:
                break
            targets.append(stream)
            tasks.append(asyncio.create_task(stream_probe.probe(url)))

        if tasks:
            results = await asyncio.gather(*tasks)
            for stream, meta in zip(targets, results):
                if not meta:
                    continue
                langs = [lang for lang in (meta.get("langs") or []) if lang]
                has_bg_subs = any(l.startswith("bg") or l.startswith("bul") for l in langs)
                if langs:
                    stream["subtitleLangs"] = ",".join(langs)
                    for lang in langs:
                        stream[f"subs_{lang}"] = True
                    # Also push a visual tag for Bulgarian subs so formatters can detect it using built-in fields
                    if has_bg_subs:
                        tags = stream.get("visualTags") or []
                        if "bg-subs" not in tags:
                            tags.append("bg-subs")
                        stream["visualTags"] = tags
                tracks = meta.get("tracks") or []
                if tracks:
                    stream["embeddedSubtitles"] = tracks
                # Re-apply marker after probe results
                _mark_bg_subs(stream)
    else:
        # Level 1: Only check upstream metadata, no probing
        logger.info(f"Stream enrichment level 1: Scraper check only (no video probing)")
        for stream in streams:
            _mark_bg_subs(stream)

    # Level 1+: Query BG subtitles scraper once per title to tag streams lacking embedded BG
    bg_scraped = False
    if media_type and item_id and request_base:
        try:
            url = f"{request_base}/bg/subtitles/{media_type}/{item_id}.json?limit=1"
            # Use a short timeout for enrichment to prevent stream loading delays
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    results = data if isinstance(data, list) else data.get("subtitles") or data.get("streams") or []
                    if results:
                        bg_scraped = True
        except Exception:
            bg_scraped = False

    if bg_scraped:
        for stream in streams:
            # Skip if already flagged via embedded/meta
            if stream.get("subs_bg") or ("bg-subs" in (stream.get("visualTags") or [])):
                continue
            stream["subs_bg"] = True
            tags = stream.get("visualTags") or []
            if "bg-subs" not in tags:
                tags.append("bg-subs")
            if "bg-scraped" not in tags:
                tags.append("bg-scraped")
            stream["visualTags"] = tags
            try:
                name = str(stream.get("name") or "")
                if "🇧🇬" not in name:
                    stream["name"] = f"🇧🇬 {name}".strip()
            except Exception:
                pass
            try:
                desc = str(stream.get("description") or "")
                if "🇧🇬" not in desc:
                    stream["description"] = f"{desc} ⚑ 🇧🇬".strip()
            except Exception:
                pass

    # Prioritize streams: 1) any embedded subtitles present 2) BG subtitle match 3) everything else
    def _priority(stream: dict) -> int:
        tags = stream.get("visualTags") or []
        has_embedded = bool(stream.get("embeddedSubtitles"))
        has_bg_embedded = "bg-embedded" in tags
        has_scraped_bg = "bg-scraped" in tags
        has_bg = bool(
            stream.get("subs_bg")
            or ("bg-subs" in tags)
            or _subtitle_langs_has_bg(stream.get("subtitleLangs"))
        )
        if has_bg_embedded:
            return 0  # Embedded BG subs
        if has_scraped_bg or (has_bg and not has_embedded):
            return 1  # BG via scraper/metadata only
        if has_embedded:
            return 2  # Embedded (non-BG)
        return 3  # Everything else

    indexed_sorted = sorted(enumerate(streams), key=lambda pair: (_priority(pair[1]), pair[0]))
    return [stream for _, stream in indexed_sorted]
