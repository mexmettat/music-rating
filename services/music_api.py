import os
import time
from concurrent.futures import ThreadPoolExecutor
import requests
from typing import Dict, List, Optional, Any

# Simple in-memory cache to make catalog browsing & album pages super fast
_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL = 3600  # 1 hour


def _get_cache(key: str) -> Optional[Any]:
    item = _CACHE.get(key)
    if item and (time.time() - item["ts"] < CACHE_TTL):
        return item["data"]
    return None


def _set_cache(key: str, data: Any) -> None:
    _CACHE[key] = {"ts": time.time(), "data": data}


def _hi_res_artwork(url: str, size: int = 600) -> str:
    if not url:
        return "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=600&auto=format&fit=crop&q=80"
    return url.replace("100x100bb", f"{size}x{size}bb").replace("60x60bb", f"{size}x{size}bb")


def _format_duration(ms: Optional[int]) -> str:
    if not ms:
        return "0:00"
    total_sec = int(ms // 1000)
    mins = total_sec // 60
    secs = total_sec % 60
    return f"{mins}:{secs:02d}"


def _clean_release_title(title: str) -> str:
    if not title:
        return "Bilinmeyen Albüm"
    for suffix in [" - Single", " - EP"]:
        if title.endswith(suffix):
            return title[: -len(suffix)].strip()
    return title


def _detect_release_type(collection: Dict[str, Any], tracks_count: Optional[int] = None) -> str:
    cname = (collection.get("collectionName") or "").lower()
    tcount = tracks_count if tracks_count is not None else collection.get("trackCount", 0)
    if "- single" in cname or tcount <= 1:
        return "single"
    if "- ep" in cname and tcount <= 3:
        return "single"
    return "album"


# Curated fallback & starter showcase queries
CURATED_CATEGORIES = {
    "trending": {
        "label": "Trend & Popüler",
        "queries": ["The Weeknd After Hours", "Daft Punk Random Access Memories", "Tame Impala Currents", "Arctic Monkeys AM", "Kendrick Lamar DAMN", "Billie Eilish Hit Me Hard and Soft", "Tarkan Karma", "Mabel Matiz Maya", "Mor ve Ötesi Dünya Yalan Söylüyor", "Radiohead OK Computer", "Dua Lipa Future Nostalgia", "Pink Floyd Dark Side of the Moon"]
    },
    "turkish": {
        "label": "Türkçe Müzik",
        "queries": ["Mor ve Ötesi Dünya Yalan Söylüyor", "Mabel Matiz Fatih", "Şebnem Ferah Od", "Duman Belki Alışman Lazım", "Tarkan Karma", "Teoman Renkli Rüyalar Oteli", "Büyük Ev Ablukada Fırtınayt", "Sezen Aksu Gülümse", "Ceza Med Cezir", "Hayko Cepkin Tanışma Bitti", "Jakuzi Fantezi Müzik", "Adamlar Dünya Günlükleri"]
    },
    "rock_alt": {
        "label": "Rock & Alternatif",
        "queries": ["Radiohead In Rainbows", "Arctic Monkeys AM", "The Strokes The New Abnormal", "Nirvana Nevermind", "Linkin Park Hybrid Theory", "Pink Floyd Wish You Were Here", "Muse Absolution", "Deftones White Pony", "Gorillaz Demon Days", "Tame Impala Lonerism"]
    },
    "hiphop_rnb": {
        "label": "Hip-Hop & R&B",
        "queries": ["Kendrick Lamar good kid m.A.A.d city", "Travis Scott ASTROWORLD", "Frank Ocean Blonde", "Kanye West My Beautiful Dark Twisted Fantasy", "Tyler The Creator IGOR", "SZA SOS", "The Weeknd Dawn FM", "Metro Boomin Heroes Villains"]
    },
    "singles": {
        "label": "Popüler Single'lar",
        "queries": ["The Weeknd Blinding Lights", "Daft Punk Get Lucky", "Tame Impala The Less I Know The Better", "Billie Eilish Birds of a Feather", "Arctic Monkeys Do I Wanna Know", "Kendrick Lamar Not Like Us", "Dua Lipa Levitating", "Mor ve Ötesi Bir Derdim Var"]
    }
}


def search_catalog(query: str, filter_type: str = "all", limit: int = 50) -> List[Dict[str, Any]]:
    """
    Searches Apple Music / iTunes API for albums and singles with smart artist discography lookup.
    filter_type: 'all', 'album', or 'single'
    """
    query = (query or "").strip()
    if not query:
        return []

    cache_key = f"search:{filter_type}:{limit}:{query.lower()}"
    cached = _get_cache(cache_key)
    if cached is not None:
        return cached

    results: List[Dict[str, Any]] = []
    seen_ids = set()

    try:
        # Step A: If user is searching an artist (e.g. "charli xcx"), lookup their artist discography
        # This returns all real studio albums (BRAT, Crash, Pop 2, Sucker etc.) that keyword search buries under 100 singles!
        if filter_type in ("all", "album"):
            try:
                artist_resp = requests.get(
                    "https://itunes.apple.com/search",
                    params={
                        "term": query,
                        "entity": "musicArtist",
                        "limit": 2,
                    },
                    timeout=4,
                )
                if artist_resp.status_code == 200:
                    for aitem in artist_resp.json().get("results", []):
                        aid = aitem.get("artistId")
                        aname = aitem.get("artistName", "").lower()
                        # If query closely matches artist name
                        if aid and (query.lower() in aname or aname in query.lower()):
                            discog_resp = requests.get(
                                "https://itunes.apple.com/lookup",
                                params={
                                    "id": aid,
                                    "entity": "album",
                                    "limit": 100,
                                },
                                timeout=5,
                            )
                            if discog_resp.status_code == 200:
                                for ditem in discog_resp.json().get("results", []):
                                    if ditem.get("wrapperType") != "collection":
                                        continue
                                    col_id = ditem.get("collectionId")
                                    if not col_id:
                                        continue
                                    rtype = _detect_release_type(ditem)
                                    if filter_type == "album" and rtype != "album":
                                        continue
                                    if filter_type == "single" and rtype != "single":
                                        continue
                                    rel_id = f"itunes_{col_id}"
                                    if rel_id in seen_ids:
                                        continue
                                    seen_ids.add(rel_id)
                                    release_date = ditem.get("releaseDate", "")
                                    year = release_date[:4] if release_date else ""
                                    results.append({
                                        "release_id": rel_id,
                                        "source_id": str(col_id),
                                        "release_type": rtype,
                                        "title": _clean_release_title(ditem.get("collectionName", "")),
                                        "raw_title": ditem.get("collectionName", ""),
                                        "artist": ditem.get("artistName", "Bilinmeyen Sanatçı"),
                                        "artwork_url": _hi_res_artwork(ditem.get("artworkUrl100", "")),
                                        "year": year,
                                        "genre": ditem.get("primaryGenreName", "Müzik"),
                                        "track_count": ditem.get("trackCount", 1),
                                        "apple_url": ditem.get("collectionViewUrl", ""),
                                    })
            except Exception as e:
                print(f"[music_api] artist discography lookup error: {e}")

        # Step B: General Album Search with higher limit (fetch up to 100 to catch true albums)
        if filter_type in ("all", "album", "single") and len(results) < limit:
            album_fetch_limit = 100 if filter_type == "album" else 50
            resp = requests.get(
                "https://itunes.apple.com/search",
                params={
                    "term": query,
                    "media": "music",
                    "entity": "album",
                    "limit": album_fetch_limit,
                },
                timeout=6,
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("results", []):
                    col_id = item.get("collectionId")
                    if not col_id:
                        continue
                    rtype = _detect_release_type(item)
                    if filter_type == "album" and rtype != "album":
                        continue
                    if filter_type == "single" and rtype != "single":
                        continue
                    rel_id = f"itunes_{col_id}"
                    if rel_id in seen_ids:
                        continue
                    seen_ids.add(rel_id)
                    release_date = item.get("releaseDate", "")
                    year = release_date[:4] if release_date else ""
                    results.append({
                        "release_id": rel_id,
                        "source_id": str(col_id),
                        "release_type": rtype,
                        "title": _clean_release_title(item.get("collectionName", "")),
                        "raw_title": item.get("collectionName", ""),
                        "artist": item.get("artistName", "Bilinmeyen Sanatçı"),
                        "artwork_url": _hi_res_artwork(item.get("artworkUrl100", "")),
                        "year": year,
                        "genre": item.get("primaryGenreName", "Müzik"),
                        "track_count": item.get("trackCount", 1),
                        "apple_url": item.get("collectionViewUrl", ""),
                    })

        # Step C: Fetch Songs as Singles when filter_type is 'single' or 'all'
        if filter_type in ("all", "single") and len(results) < limit:
            song_limit = 24 if filter_type == "all" else 50
            resp_songs = requests.get(
                "https://itunes.apple.com/search",
                params={
                    "term": query,
                    "media": "music",
                    "entity": "song",
                    "limit": song_limit,
                },
                timeout=6,
            )
            if resp_songs.status_code == 200:
                sdata = resp_songs.json()
                for sitem in sdata.get("results", []):
                    track_id = sitem.get("trackId")
                    if not track_id:
                        continue
                    rel_id = f"itunes_single_{track_id}"
                    if rel_id in seen_ids:
                        continue
                    seen_ids.add(rel_id)
                    release_date = sitem.get("releaseDate", "")
                    year = release_date[:4] if release_date else ""
                    results.append({
                        "release_id": rel_id,
                        "source_id": str(track_id),
                        "release_type": "single",
                        "title": sitem.get("trackName", "Bilinmeyen Şarkı"),
                        "raw_title": sitem.get("trackName", ""),
                        "artist": sitem.get("artistName", "Bilinmeyen Sanatçı"),
                        "album_name": _clean_release_title(sitem.get("collectionName", "")),
                        "artwork_url": _hi_res_artwork(sitem.get("artworkUrl100", "")),
                        "year": year,
                        "genre": sitem.get("primaryGenreName", "Müzik"),
                        "track_count": 1,
                        "preview_url": sitem.get("previewUrl", ""),
                        "apple_url": sitem.get("trackViewUrl", ""),
                    })
    except Exception as e:
        print(f"[music_api] search_catalog error: {e}")

    _set_cache(cache_key, results)
    return results


def get_curated_catalog(category: str = "trending") -> List[Dict[str, Any]]:
    """
    Returns a curated catalog list for the homepage shelves.
    """
    cache_key = f"curated:{category}"
    cached = _get_cache(cache_key)
    if cached is not None:
        return cached

    cat_info = CURATED_CATEGORIES.get(category, CURATED_CATEGORIES["trending"])
    queries = cat_info["queries"]
    is_single_cat = category == "singles"

    items: List[Dict[str, Any]] = []
    seen = set()

    def _fetch_one(q: str) -> Optional[Dict[str, Any]]:
        try:
            entity = "song" if is_single_cat else "album"
            resp = requests.get(
                "https://itunes.apple.com/search",
                params={
                    "term": q,
                    "media": "music",
                    "entity": entity,
                    "limit": 1,
                    "country": "TR",
                },
                timeout=4,
            )
            if resp.status_code == 200:
                res_list = resp.json().get("results", [])
                if res_list:
                    it = res_list[0]
                    if is_single_cat:
                        tid = it.get("trackId")
                        if tid:
                            rdate = it.get("releaseDate", "")
                            return {
                                "release_id": f"itunes_single_{tid}",
                                "source_id": str(tid),
                                "release_type": "single",
                                "title": it.get("trackName", ""),
                                "artist": it.get("artistName", ""),
                                "artwork_url": _hi_res_artwork(it.get("artworkUrl100", "")),
                                "year": rdate[:4] if rdate else "",
                                "genre": it.get("primaryGenreName", "Müzik"),
                                "track_count": 1,
                                "preview_url": it.get("previewUrl", ""),
                            }
                    else:
                        cid = it.get("collectionId")
                        if cid:
                            rdate = it.get("releaseDate", "")
                            rtype = _detect_release_type(it)
                            return {
                                "release_id": f"itunes_{cid}",
                                "source_id": str(cid),
                                "release_type": rtype,
                                "title": _clean_release_title(it.get("collectionName", "")),
                                "artist": it.get("artistName", ""),
                                "artwork_url": _hi_res_artwork(it.get("artworkUrl100", "")),
                                "year": rdate[:4] if rdate else "",
                                "genre": it.get("primaryGenreName", "Müzik"),
                                "track_count": it.get("trackCount", 1),
                            }
        except Exception as e:
            print(f"[music_api] _fetch_one error ({q}): {e}")
        return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        fetched = list(executor.map(_fetch_one, queries[:12]))

    for res in fetched:
        if res and res["release_id"] not in seen:
            seen.add(res["release_id"])
            items.append(res)

    if items:
        _set_cache(cache_key, items)
    return items


def get_release_details(release_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetches full details of an album or single by its release_id:
    - 'itunes_<collectionId>' -> Album or Single collection with all tracks
    - 'itunes_single_<trackId>' -> Standalone Single track
    """
    cache_key = f"release:{release_id}"
    cached = _get_cache(cache_key)
    if cached is not None:
        return cached

    try:
        if release_id.startswith("itunes_single_"):
            track_id = release_id.replace("itunes_single_", "").strip()
            resp = requests.get(
                "https://itunes.apple.com/lookup",
                params={"id": track_id, "country": "TR"},
                timeout=6,
            )
            if resp.status_code != 200:
                return None
            results = resp.json().get("results", [])
            if not results:
                return None
            t = results[0]
            rdate = t.get("releaseDate", "")
            parent_col_id = t.get("collectionId")
            details = {
                "release_id": release_id,
                "source_id": str(track_id),
                "release_type": "single",
                "title": t.get("trackName", "Bilinmeyen Single"),
                "raw_title": t.get("trackName", ""),
                "artist": t.get("artistName", "Bilinmeyen Sanatçı"),
                "artist_id": t.get("artistId"),
                "parent_album_id": f"itunes_{parent_col_id}" if parent_col_id else None,
                "parent_album_title": _clean_release_title(t.get("collectionName", "")),
                "artwork_url": _hi_res_artwork(t.get("artworkUrl100", ""), 600),
                "year": rdate[:4] if rdate else "",
                "release_date": rdate[:10] if rdate else "",
                "genre": t.get("primaryGenreName", "Müzik"),
                "copyright": t.get("copyright", ""),
                "apple_url": t.get("trackViewUrl", ""),
                "preview_url": t.get("previewUrl", ""),
                "duration": _format_duration(t.get("trackTimeMillis")),
                "track_count": 1,
                "tracks": [
                    {
                        "track_id": f"track_{track_id}",
                        "track_number": 1,
                        "disc_number": 1,
                        "title": t.get("trackName", ""),
                        "artist": t.get("artistName", ""),
                        "duration": _format_duration(t.get("trackTimeMillis")),
                        "duration_ms": t.get("trackTimeMillis", 0),
                        "preview_url": t.get("previewUrl", ""),
                        "single_release_id": release_id,
                    }
                ],
            }
            _set_cache(cache_key, details)
            return details

        elif release_id.startswith("itunes_"):
            col_id = release_id.replace("itunes_", "").strip()
            resp = requests.get(
                "https://itunes.apple.com/lookup",
                params={"id": col_id, "entity": "song", "limit": 200, "country": "TR"},
                timeout=6,
            )
            if resp.status_code != 200:
                return None
            results = resp.json().get("results", [])
            if not results:
                return None

            col_info = None
            tracks = []
            for item in results:
                wtype = item.get("wrapperType")
                if wtype == "collection" and not col_info:
                    col_info = item
                elif wtype == "track" and item.get("kind") == "song":
                    tid = item.get("trackId")
                    tracks.append({
                        "track_id": f"track_{tid}",
                        "raw_track_id": str(tid),
                        "single_release_id": f"itunes_single_{tid}",
                        "track_number": item.get("trackNumber", len(tracks) + 1),
                        "disc_number": item.get("discNumber", 1),
                        "title": item.get("trackName", "İsimsiz Şarkı"),
                        "artist": item.get("artistName", ""),
                        "duration": _format_duration(item.get("trackTimeMillis")),
                        "duration_ms": item.get("trackTimeMillis", 0),
                        "preview_url": item.get("previewUrl", ""),
                    })

            if not col_info:
                # Sometimes lookup returns a single track if a trackId was passed to itunes_<id>
                first = results[0]
                if first.get("wrapperType") == "track":
                    return get_release_details(f"itunes_single_{first.get('trackId')}")
                return None

            tracks.sort(key=lambda x: (x.get("disc_number", 1), x.get("track_number", 1)))
            rtype = _detect_release_type(col_info, len(tracks) if tracks else col_info.get("trackCount", 1))
            rdate = col_info.get("releaseDate", "")
            first_preview = tracks[0]["preview_url"] if tracks else ""

            details = {
                "release_id": release_id,
                "source_id": str(col_id),
                "release_type": rtype,
                "title": _clean_release_title(col_info.get("collectionName", "Bilinmeyen Albüm")),
                "raw_title": col_info.get("collectionName", ""),
                "artist": col_info.get("artistName", "Bilinmeyen Sanatçı"),
                "artist_id": col_info.get("artistId"),
                "artwork_url": _hi_res_artwork(col_info.get("artworkUrl100", ""), 600),
                "year": rdate[:4] if rdate else "",
                "release_date": rdate[:10] if rdate else "",
                "genre": col_info.get("primaryGenreName", "Müzik"),
                "copyright": col_info.get("copyright", ""),
                "apple_url": col_info.get("collectionViewUrl", ""),
                "preview_url": first_preview,
                "track_count": len(tracks) or col_info.get("trackCount", 1),
                "tracks": tracks,
            }
            _set_cache(cache_key, details)
            return details

    except Exception as e:
        print(f"[music_api] get_release_details error for {release_id}: {e}")

    return None
