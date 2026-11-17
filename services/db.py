import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import requests
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv(override=True)


def _get_supabase_config() -> Dict[str, str]:
    load_dotenv(override=True)
    url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.getenv("SUPABASE_KEY") or "").strip()
    return {"url": url, "key": key}


def _supabase_headers(key: str, prefer: str = "return=representation") -> Dict[str, str]:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }


# SQLite Fallback Configuration (works locally and in serverless /tmp)
def _get_sqlite_path() -> str:
    base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    try:
        os.makedirs(base_dir, exist_ok=True)
        test_file = os.path.join(base_dir, ".write_test")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        return os.path.join(base_dir, "sonora.db")
    except Exception:
        return os.path.join(tempfile.gettempdir(), "sonora.db")


SQLITE_PATH = _get_sqlite_path()


def _get_sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_sqlite_db() -> None:
    conn = _get_sqlite_conn()
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            bio TEXT DEFAULT '',
            avatar_color TEXT DEFAULT '#8b5cf6',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS release_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            release_id TEXT NOT NULL,
            release_type TEXT NOT NULL,
            release_title TEXT NOT NULL,
            artist_name TEXT NOT NULL,
            artwork_url TEXT DEFAULT '',
            release_year TEXT DEFAULT '',
            genre TEXT DEFAULT '',
            score_production REAL NOT NULL,
            score_lyrics REAL NOT NULL,
            score_melody REAL NOT NULL,
            score_vocals REAL NOT NULL,
            score_replay REAL NOT NULL,
            overall_score REAL NOT NULL,
            review_text TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, release_id)
        );

        CREATE TABLE IF NOT EXISTS track_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            release_id TEXT NOT NULL,
            track_id TEXT NOT NULL,
            track_number INTEGER DEFAULT 1,
            track_title TEXT NOT NULL,
            artist_name TEXT NOT NULL,
            release_title TEXT DEFAULT '',
            artwork_url TEXT DEFAULT '',
            score REAL NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, track_id)
        );

        CREATE TABLE IF NOT EXISTS grammy_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            category_id TEXT NOT NULL,
            winner_pick TEXT DEFAULT '',
            favorite_pick TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, category_id)
        );
        """
    )
    conn.commit()
    conn.close()


init_sqlite_db()


def check_db_status() -> Dict[str, Any]:
    """
    Checks if Supabase URL & Key are configured and whether tables are reachable.
    """
    cfg = _get_supabase_config()
    if not cfg["url"] or not cfg["key"]:
        return {
            "mode": "sqlite",
            "supabase_configured": False,
            "supabase_connected": False,
            "message": "Supabase henüz .env dosyasında tanımlanmadı. Veriler şu an yerel SQLite veritabanına kaydediliyor.",
        }

    try:
        resp = requests.get(
            f"{cfg['url']}/rest/v1/users?select=id&limit=1",
            headers=_supabase_headers(cfg["key"]),
            timeout=4,
        )
        if resp.status_code == 200:
            return {
                "mode": "supabase",
                "supabase_configured": True,
                "supabase_connected": True,
                "message": "Supabase Cloud bağlantısı aktif ve tablolar hazır.",
            }
        elif resp.status_code == 404 or "relation" in resp.text.lower() or "PGRST" in resp.text:
            return {
                "mode": "sqlite",
                "supabase_configured": True,
                "supabase_connected": False,
                "message": "Supabase anahtarları algılandı ancak tablolar henüz oluşturulmamış. Lütfen supabase_schema.sql dosyasını Supabase SQL Editor'de çalıştırın.",
            }
        else:
            return {
                "mode": "sqlite",
                "supabase_configured": True,
                "supabase_connected": False,
                "message": f"Supabase yanıt kodu: {resp.status_code}. Lütfen URL ve API Key bilgilerinizi kontrol edin.",
            }
    except Exception as e:
        return {
            "mode": "sqlite",
            "supabase_configured": True,
            "supabase_connected": False,
            "message": f"Supabase bağlantı hatası: {str(e)}",
        }


def _use_supabase() -> bool:
    status = check_db_status()
    return status["supabase_connected"]


# ============================================================================
# USER AUTHENTICATION FUNCTIONS
# ============================================================================

AVATAR_COLORS = ["#8b5cf6", "#ec4899", "#06b6d4", "#10b981", "#f59e0b", "#6366f1", "#f43f5e"]


def create_user(username: str, email: str, password: str, bio: str = "") -> Dict[str, Any]:
    username = username.strip()
    email = email.strip().lower()
    pw_hash = generate_password_hash(password)
    color = AVATAR_COLORS[ len(username) % len(AVATAR_COLORS) ]
    now_iso = datetime.now(timezone.utc).isoformat()

    if _use_supabase():
        cfg = _get_supabase_config()
        # Check existing
        chk = requests.get(
            f"{cfg['url']}/rest/v1/users?or=(username.ilike.{username},email.ilike.{email})&select=id,username,email",
            headers=_supabase_headers(cfg["key"]),
            timeout=5,
        )
        if chk.status_code == 200 and chk.json():
            return {"ok": False, "error": "Bu kullanıcı adı veya e-posta adresi zaten kullanımda."}

        payload = {
            "username": username,
            "email": email,
            "password_hash": pw_hash,
            "bio": bio,
            "avatar_color": color,
            "created_at": now_iso,
        }
        resp = requests.post(
            f"{cfg['url']}/rest/v1/users",
            headers=_supabase_headers(cfg["key"]),
            json=payload,
            timeout=5,
        )
        if resp.status_code in (200, 201) and resp.json():
            user = resp.json()[0]
            return {"ok": True, "user": user}
        return {"ok": False, "error": "Kayıt sırasında bir hata oluştu."}

    # SQLite fallback
    conn = _get_sqlite_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM users WHERE LOWER(username) = LOWER(?) OR LOWER(email) = LOWER(?)",
            (username, email),
        )
        if cur.fetchone():
            return {"ok": False, "error": "Bu kullanıcı adı veya e-posta adresi zaten kullanımda."}
        cur.execute(
            """
            INSERT INTO users (username, email, password_hash, bio, avatar_color, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (username, email, pw_hash, bio, color, now_iso),
        )
        conn.commit()
        uid = cur.lastrowid
        cur.execute("SELECT * FROM users WHERE id = ?", (uid,))
        row = dict(cur.fetchone())
        return {"ok": True, "user": row}
    finally:
        conn.close()


def authenticate_user(identifier: str, password: str) -> Dict[str, Any]:
    identifier = identifier.strip()
    if _use_supabase():
        cfg = _get_supabase_config()
        resp = requests.get(
            f"{cfg['url']}/rest/v1/users?or=(username.ilike.{identifier},email.ilike.{identifier})&select=*&limit=1",
            headers=_supabase_headers(cfg["key"]),
            timeout=5,
        )
        if resp.status_code == 200 and resp.json():
            user = resp.json()[0]
            if check_password_hash(user["password_hash"], password):
                return {"ok": True, "user": user}
        return {"ok": False, "error": "Kullanıcı adı/e-posta veya şifre hatalı."}

    conn = _get_sqlite_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(?) OR LOWER(email) = LOWER(?)",
            (identifier, identifier),
        )
        row = cur.fetchone()
        if row and check_password_hash(row["password_hash"], password):
            return {"ok": True, "user": dict(row)}
        return {"ok": False, "error": "Kullanıcı adı/e-posta veya şifre hatalı."}
    finally:
        conn.close()


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    if _use_supabase():
        cfg = _get_supabase_config()
        resp = requests.get(
            f"{cfg['url']}/rest/v1/users?username=ilike.{username}&select=id,username,email,bio,avatar_color,created_at&limit=1",
            headers=_supabase_headers(cfg["key"]),
            timeout=5,
        )
        if resp.status_code == 200 and resp.json():
            return resp.json()[0]
        return None

    conn = _get_sqlite_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, username, email, bio, avatar_color, created_at FROM users WHERE LOWER(username) = LOWER(?)",
            (username,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ============================================================================
# RELEASE RATINGS (5 CRITERIA FOR ALBUMS & SINGLES AS A WHOLE)
# ============================================================================

def upsert_release_rating(
    user_id: int,
    username: str,
    release_id: str,
    release_type: str,
    release_title: str,
    artist_name: str,
    artwork_url: str,
    release_year: str,
    genre: str,
    score_production: float,
    score_lyrics: float,
    score_melody: float,
    score_vocals: float,
    score_replay: float,
    review_text: str = "",
) -> Dict[str, Any]:
    scores = [score_production, score_lyrics, score_melody, score_vocals, score_replay]
    clamped = [max(1.0, min(10.0, round(float(s), 1))) for s in scores]
    sp, sl, sm, sv, sr = clamped
    overall = round(sum(clamped) / 5.0, 2)
    now_iso = datetime.now(timezone.utc).isoformat()

    payload = {
        "user_id": int(user_id),
        "username": username,
        "release_id": release_id,
        "release_type": release_type,
        "release_title": release_title,
        "artist_name": artist_name,
        "artwork_url": artwork_url,
        "release_year": str(release_year or ""),
        "genre": str(genre or ""),
        "score_production": sp,
        "score_lyrics": sl,
        "score_melody": sm,
        "score_vocals": sv,
        "score_replay": sr,
        "overall_score": overall,
        "review_text": (review_text or "").strip(),
        "updated_at": now_iso,
    }

    if _use_supabase():
        cfg = _get_supabase_config()
        resp = requests.post(
            f"{cfg['url']}/rest/v1/release_ratings?on_conflict=user_id,release_id",
            headers=_supabase_headers(cfg["key"], prefer="resolution=merge-duplicates,return=representation"),
            json=payload,
            timeout=5,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            return {"ok": True, "rating": data[0] if data else payload, "overall_score": overall}
        return {"ok": False, "error": "Puan kaydedilirken bir hata oluştu."}

    conn = _get_sqlite_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO release_ratings (
                user_id, username, release_id, release_type, release_title, artist_name,
                artwork_url, release_year, genre,
                score_production, score_lyrics, score_melody, score_vocals, score_replay,
                overall_score, review_text, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, release_id) DO UPDATE SET
                score_production = excluded.score_production,
                score_lyrics = excluded.score_lyrics,
                score_melody = excluded.score_melody,
                score_vocals = excluded.score_vocals,
                score_replay = excluded.score_replay,
                overall_score = excluded.overall_score,
                review_text = excluded.review_text,
                updated_at = excluded.updated_at
            """,
            (
                int(user_id), username, release_id, release_type, release_title, artist_name,
                artwork_url, str(release_year or ""), str(genre or ""),
                sp, sl, sm, sv, sr, overall, (review_text or "").strip(), now_iso,
            ),
        )
        conn.commit()
        return {"ok": True, "rating": payload, "overall_score": overall}
    finally:
        conn.close()


def get_release_ratings_data(release_id: str, current_user_id: Optional[int] = None) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    if _use_supabase():
        cfg = _get_supabase_config()
        resp = requests.get(
            f"{cfg['url']}/rest/v1/release_ratings?release_id=eq.{release_id}&order=updated_at.desc",
            headers=_supabase_headers(cfg["key"]),
            timeout=5,
        )
        if resp.status_code == 200:
            rows = resp.json()
    else:
        conn = _get_sqlite_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM release_ratings WHERE release_id = ? ORDER BY updated_at DESC",
                (release_id,),
            )
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    count = len(rows)
    user_rating = None
    if current_user_id is not None:
        for r in rows:
            if int(r["user_id"]) == int(current_user_id):
                user_rating = r
                break

    if count == 0:
        return {
            "count": 0,
            "avg_overall": None,
            "avg_production": 0,
            "avg_lyrics": 0,
            "avg_melody": 0,
            "avg_vocals": 0,
            "avg_replay": 0,
            "reviews": [],
            "user_rating": None,
        }

    avg_overall = round(sum(float(r["overall_score"]) for r in rows) / count, 2)
    avg_prod = round(sum(float(r["score_production"]) for r in rows) / count, 1)
    avg_lyr = round(sum(float(r["score_lyrics"]) for r in rows) / count, 1)
    avg_mel = round(sum(float(r["score_melody"]) for r in rows) / count, 1)
    avg_voc = round(sum(float(r["score_vocals"]) for r in rows) / count, 1)
    avg_rep = round(sum(float(r["score_replay"]) for r in rows) / count, 1)

    return {
        "count": count,
        "avg_overall": avg_overall,
        "avg_production": avg_prod,
        "avg_lyrics": avg_lyr,
        "avg_melody": avg_mel,
        "avg_vocals": avg_voc,
        "avg_replay": avg_rep,
        "reviews": rows,
        "user_rating": user_rating,
    }


# ============================================================================
# TRACK RATINGS (SINGLE 1-10 SCORE FOR INDIVIDUAL SONGS IN AN ALBUM)
# ============================================================================

def upsert_track_rating(
    user_id: int,
    username: str,
    release_id: str,
    track_id: str,
    track_number: int,
    track_title: str,
    artist_name: str,
    release_title: str,
    artwork_url: str,
    score: float,
) -> Dict[str, Any]:
    clamped_score = max(1.0, min(10.0, round(float(score), 1)))
    now_iso = datetime.now(timezone.utc).isoformat()

    payload = {
        "user_id": int(user_id),
        "username": username,
        "release_id": release_id,
        "track_id": track_id,
        "track_number": int(track_number or 1),
        "track_title": track_title,
        "artist_name": artist_name,
        "release_title": release_title,
        "artwork_url": artwork_url,
        "score": clamped_score,
        "updated_at": now_iso,
    }

    if _use_supabase():
        cfg = _get_supabase_config()
        resp = requests.post(
            f"{cfg['url']}/rest/v1/track_ratings?on_conflict=user_id,track_id",
            headers=_supabase_headers(cfg["key"], prefer="resolution=merge-duplicates,return=representation"),
            json=payload,
            timeout=5,
        )
        if resp.status_code in (200, 201):
            return {"ok": True, "score": clamped_score}
        return {"ok": False, "error": "Şarkı puanı kaydedilirken bir hata oluştu."}

    conn = _get_sqlite_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO track_ratings (
                user_id, username, release_id, track_id, track_number,
                track_title, artist_name, release_title, artwork_url, score, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, track_id) DO UPDATE SET
                score = excluded.score,
                updated_at = excluded.updated_at
            """,
            (
                int(user_id), username, release_id, track_id, int(track_number or 1),
                track_title, artist_name, release_title, artwork_url, clamped_score, now_iso,
            ),
        )
        conn.commit()
        return {"ok": True, "score": clamped_score}
    finally:
        conn.close()


def get_album_track_ratings_summary(release_id: str, current_user_id: Optional[int] = None) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    if _use_supabase():
        cfg = _get_supabase_config()
        resp = requests.get(
            f"{cfg['url']}/rest/v1/track_ratings?release_id=eq.{release_id}",
            headers=_supabase_headers(cfg["key"]),
            timeout=5,
        )
        if resp.status_code == 200:
            rows = resp.json()
    else:
        conn = _get_sqlite_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM track_ratings WHERE release_id = ?", (release_id,))
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    by_track: Dict[str, List[float]] = {}
    user_tracks: Dict[str, float] = {}

    for r in rows:
        tid = r["track_id"]
        sc = float(r["score"])
        by_track.setdefault(tid, []).append(sc)
        if current_user_id is not None and int(r["user_id"]) == int(current_user_id):
            user_tracks[tid] = sc

    track_stats: Dict[str, Dict[str, Any]] = {}
    all_avgs: List[float] = []
    for tid, sc_list in by_track.items():
        avg_sc = round(sum(sc_list) / len(sc_list), 1)
        track_stats[tid] = {"avg": avg_sc, "count": len(sc_list)}
        all_avgs.append(avg_sc)

    album_tracks_avg = round(sum(all_avgs) / len(all_avgs), 2) if all_avgs else None
    user_tracks_avg = round(sum(user_tracks.values()) / len(user_tracks), 2) if user_tracks else None

    return {
        "track_stats": track_stats,
        "user_tracks": user_tracks,
        "album_tracks_avg": album_tracks_avg,
        "user_tracks_avg": user_tracks_avg,
        "total_track_votes": len(rows),
    }


# ============================================================================
# COMMUNITY FEED, LEADERBOARD & USER PROFILE QUERIES
# ============================================================================

def get_recent_reviews(limit: int = 10) -> List[Dict[str, Any]]:
    if _use_supabase():
        cfg = _get_supabase_config()
        resp = requests.get(
            f"{cfg['url']}/rest/v1/release_ratings?order=updated_at.desc&limit={limit}",
            headers=_supabase_headers(cfg["key"]),
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json()
        return []

    conn = _get_sqlite_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM release_ratings ORDER BY updated_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_community_rated_releases(
    sort_by: str = "newest",
    genre_filter: str = "all",
    rtype_filter: str = "all",
) -> Dict[str, Any]:
    """
    Aggregates all albums & singles rated by users on the platform.
    Supports sorting:
      - 'newest' (default: most recently rated/reviewed first)
      - 'score_desc' (highest average score first)
      - 'score_asc' (lowest average score first)
      - 'most_reviewed' (most ratings count first)
    Supports filtering by genre and release_type ('album' / 'single').
    """
    rows: List[Dict[str, Any]] = []
    if _use_supabase():
        cfg = _get_supabase_config()
        resp = requests.get(
            f"{cfg['url']}/rest/v1/release_ratings?select=*&order=updated_at.desc&limit=500",
            headers=_supabase_headers(cfg["key"]),
            timeout=5,
        )
        if resp.status_code == 200:
            rows = resp.json()
    else:
        conn = _get_sqlite_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM release_ratings ORDER BY updated_at DESC")
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    grouped: Dict[str, Dict[str, Any]] = {}
    genres_set = set()

    for r in rows:
        rid = r["release_id"]
        g = (r.get("genre") or "").strip()
        if g:
            genres_set.add(g)

        if rid not in grouped:
            grouped[rid] = {
                "release_id": rid,
                "release_type": r.get("release_type", "album"),
                "title": r.get("release_title", "Bilinmeyen Yapım"),
                "artist": r.get("artist_name", "Bilinmeyen Sanatçı"),
                "artwork_url": r.get("artwork_url", ""),
                "year": r.get("release_year", ""),
                "genre": g or "Müzik",
                "latest_updated_at": r.get("updated_at", ""),
                "latest_username": r.get("username", ""),
                "latest_review": r.get("review_text", ""),
                "latest_user_score": float(r.get("overall_score", 0)),
                "scores": [],
                "prod": [],
                "lyr": [],
                "mel": [],
                "voc": [],
                "rep": [],
            }
        else:
            # Since rows are ordered by updated_at DESC, the first row seen has the latest timestamp,
            # but if an earlier row had no review text and a newer one has text, keep latest info accurate
            if r.get("updated_at", "") > grouped[rid]["latest_updated_at"]:
                grouped[rid]["latest_updated_at"] = r.get("updated_at", "")
                grouped[rid]["latest_username"] = r.get("username", "")
                grouped[rid]["latest_user_score"] = float(r.get("overall_score", 0))
            if not grouped[rid]["latest_review"] and r.get("review_text"):
                grouped[rid]["latest_review"] = r.get("review_text", "")
                grouped[rid]["latest_username"] = r.get("username", "")

        grouped[rid]["scores"].append(float(r["overall_score"]))
        grouped[rid]["prod"].append(float(r["score_production"]))
        grouped[rid]["lyr"].append(float(r["score_lyrics"]))
        grouped[rid]["mel"].append(float(r["score_melody"]))
        grouped[rid]["voc"].append(float(r["score_vocals"]))
        grouped[rid]["rep"].append(float(r["score_replay"]))

    items: List[Dict[str, Any]] = []
    for rid, info in grouped.items():
        if genre_filter and genre_filter != "all":
            if info["genre"].lower() != genre_filter.lower():
                continue
        if rtype_filter in ("album", "single"):
            if info["release_type"] != rtype_filter:
                continue

        cnt = len(info["scores"])
        items.append({
            "release_id": rid,
            "release_type": info["release_type"],
            "title": info["title"],
            "artist": info["artist"],
            "artwork_url": info["artwork_url"],
            "year": info["year"],
            "genre": info["genre"],
            "latest_updated_at": info["latest_updated_at"],
            "latest_username": info["latest_username"],
            "latest_review": info["latest_review"],
            "latest_user_score": info["latest_user_score"],
            "avg_score": round(sum(info["scores"]) / cnt, 2),
            "avg_production": round(sum(info["prod"]) / cnt, 1),
            "avg_lyrics": round(sum(info["lyr"]) / cnt, 1),
            "avg_melody": round(sum(info["mel"]) / cnt, 1),
            "avg_vocals": round(sum(info["voc"]) / cnt, 1),
            "avg_replay": round(sum(info["rep"]) / cnt, 1),
            "rating_count": cnt,
        })

    if sort_by == "score_desc":
        items.sort(key=lambda x: (x["avg_score"], x["rating_count"], x["latest_updated_at"]), reverse=True)
    elif sort_by == "score_asc":
        items.sort(key=lambda x: (x["avg_score"], -x["rating_count"]))
    elif sort_by == "most_reviewed":
        items.sort(key=lambda x: (x["rating_count"], x["avg_score"], x["latest_updated_at"]), reverse=True)
    else:
        # Default: 'newest' (En Yeni Puanlananlar)
        items.sort(key=lambda x: x["latest_updated_at"], reverse=True)

    return {
        "items": items,
        "genres": sorted(list(genres_set)),
        "total_count": len(grouped),
    }


def get_top_rated_releases(limit: int = 12) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if _use_supabase():
        cfg = _get_supabase_config()
        resp = requests.get(
            f"{cfg['url']}/rest/v1/release_ratings?select=*&order=overall_score.desc&limit=200",
            headers=_supabase_headers(cfg["key"]),
            timeout=5,
        )
        if resp.status_code == 200:
            rows = resp.json()
    else:
        conn = _get_sqlite_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM release_ratings")
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    grouped: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        rid = r["release_id"]
        if rid not in grouped:
            grouped[rid] = {
                "release_id": rid,
                "release_type": r["release_type"],
                "title": r["release_title"],
                "artist": r["artist_name"],
                "artwork_url": r["artwork_url"],
                "year": r.get("release_year", ""),
                "genre": r.get("genre", ""),
                "scores": [],
                "prod": [],
                "lyr": [],
                "mel": [],
                "voc": [],
                "rep": [],
            }
        grouped[rid]["scores"].append(float(r["overall_score"]))
        grouped[rid]["prod"].append(float(r["score_production"]))
        grouped[rid]["lyr"].append(float(r["score_lyrics"]))
        grouped[rid]["mel"].append(float(r["score_melody"]))
        grouped[rid]["voc"].append(float(r["score_vocals"]))
        grouped[rid]["rep"].append(float(r["score_replay"]))

    leaderboard = []
    for rid, info in grouped.items():
        cnt = len(info["scores"])
        leaderboard.append({
            "release_id": rid,
            "release_type": info["release_type"],
            "title": info["title"],
            "artist": info["artist"],
            "artwork_url": info["artwork_url"],
            "year": info["year"],
            "genre": info["genre"],
            "avg_score": round(sum(info["scores"]) / cnt, 2),
            "avg_production": round(sum(info["prod"]) / cnt, 1),
            "avg_lyrics": round(sum(info["lyr"]) / cnt, 1),
            "avg_melody": round(sum(info["mel"]) / cnt, 1),
            "avg_vocals": round(sum(info["voc"]) / cnt, 1),
            "avg_replay": round(sum(info["rep"]) / cnt, 1),
            "rating_count": cnt,
        })

    leaderboard.sort(key=lambda x: (x["avg_score"], x["rating_count"]), reverse=True)
    return leaderboard[:limit]


def get_bulk_release_stats(release_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not release_ids:
        return {}
    rows: List[Dict[str, Any]] = []
    if _use_supabase():
        cfg = _get_supabase_config()
        resp = requests.get(
            f"{cfg['url']}/rest/v1/release_ratings?select=release_id,overall_score",
            headers=_supabase_headers(cfg["key"]),
            timeout=5,
        )
        if resp.status_code == 200:
            rows = resp.json()
    else:
        conn = _get_sqlite_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT release_id, overall_score FROM release_ratings")
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    by_id: Dict[str, List[float]] = {}
    for r in rows:
        by_id.setdefault(r["release_id"], []).append(float(r["overall_score"]))

    result = {}
    for rid in release_ids:
        sc = by_id.get(rid, [])
        if sc:
            result[rid] = {"avg": round(sum(sc) / len(sc), 2), "count": len(sc)}
    return result


def get_user_profile_stats(username: str) -> Optional[Dict[str, Any]]:
    user = get_user_by_username(username)
    if not user:
        return None

    uid = user["id"]
    rel_rows: List[Dict[str, Any]] = []
    trk_rows: List[Dict[str, Any]] = []
    grammy_rows: List[Dict[str, Any]] = []

    if _use_supabase():
        cfg = _get_supabase_config()
        r1 = requests.get(
            f"{cfg['url']}/rest/v1/release_ratings?user_id=eq.{uid}&order=updated_at.desc",
            headers=_supabase_headers(cfg["key"]),
            timeout=5,
        )
        if r1.status_code == 200:
            rel_rows = r1.json()
        r2 = requests.get(
            f"{cfg['url']}/rest/v1/track_ratings?user_id=eq.{uid}&order=updated_at.desc",
            headers=_supabase_headers(cfg["key"]),
            timeout=5,
        )
        if r2.status_code == 200:
            trk_rows = r2.json()
        r3 = requests.get(
            f"{cfg['url']}/rest/v1/grammy_predictions?user_id=eq.{uid}&order=updated_at.desc",
            headers=_supabase_headers(cfg["key"]),
            timeout=5,
        )
        if r3.status_code == 200:
            grammy_rows = r3.json()
    else:
        conn = _get_sqlite_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM release_ratings WHERE user_id = ? ORDER BY updated_at DESC", (uid,))
            rel_rows = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM track_ratings WHERE user_id = ? ORDER BY updated_at DESC", (uid,))
            trk_rows = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM grammy_predictions WHERE user_id = ? ORDER BY updated_at DESC", (uid,))
            grammy_rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    rel_count = len(rel_rows)
    trk_count = len(trk_rows)
    avg_given = round(sum(float(r["overall_score"]) for r in rel_rows) / rel_count, 2) if rel_count else 0.0

    criteria_avgs = {
        "production": round(sum(float(r["score_production"]) for r in rel_rows) / rel_count, 1) if rel_count else 0.0,
        "lyrics": round(sum(float(r["score_lyrics"]) for r in rel_rows) / rel_count, 1) if rel_count else 0.0,
        "melody": round(sum(float(r["score_melody"]) for r in rel_rows) / rel_count, 1) if rel_count else 0.0,
        "vocals": round(sum(float(r["score_vocals"]) for r in rel_rows) / rel_count, 1) if rel_count else 0.0,
        "replay": round(sum(float(r["score_replay"]) for r in rel_rows) / rel_count, 1) if rel_count else 0.0,
    }

    # Enrich Grammy picks
    from services.grammy_data import GRAMMY_CATEGORIES
    nominee_map = {
        nom["id"]: nom
        for cat in GRAMMY_CATEGORIES
        for nom in cat.get("nominees", [])
    }
    category_map = {cat["id"]: cat for cat in GRAMMY_CATEGORIES}

    grammy_picks = []
    for grow in grammy_rows:
        cid = grow.get("category_id")
        w_id = grow.get("winner_pick")
        f_id = grow.get("favorite_pick")
        cat = category_map.get(cid)
        if cat and (w_id or f_id):
            grammy_picks.append({
                "category_id": cid,
                "category_title": cat["title"],
                "field_badge": cat["field_badge"],
                "winner": nominee_map.get(w_id),
                "favorite": nominee_map.get(f_id),
                "updated_at": grow.get("updated_at", ""),
            })

    return {
        "user": user,
        "release_ratings": rel_rows,
        "track_ratings": trk_rows,
        "release_count": rel_count,
        "track_count": trk_count,
        "avg_given": avg_given,
        "criteria_avgs": criteria_avgs,
        "grammy_picks": grammy_picks,
    }


def seed_initial_demo_data() -> None:
    """
    Seeds a few showcase ratings into SQLite if empty so the site looks rich immediately.
    """
    conn = _get_sqlite_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM release_ratings")
        if cur.fetchone()["cnt"] > 0:
            return

        # Create a demo critic user
        pw_hash = generate_password_hash("demo1234")
        now_iso = datetime.now(timezone.utc).isoformat()
        cur.execute(
            """
            INSERT OR IGNORE INTO users (username, email, password_hash, bio, avatar_color, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("müzikgurusu", "guru@sonora.app", pw_hash, "Albüm ve single koleksiyoneri, ses mühendisi.", "#8b5cf6", now_iso),
        )
        conn.commit()
        cur.execute("SELECT id FROM users WHERE username = ?", ("müzikgurusu",))
        user_row = cur.fetchone()
        if not user_row:
            return
        uid = user_row["id"]

        sample_releases = [
            (
                "itunes_1440857781", "album", "Random Access Memories", "Daft Punk",
                "https://is1-ssl.mzstatic.com/image/thumb/Music115/v4/e8/43/5f/e8435f09-29f5-8216-5079-4d88c4267091/886443919266.jpg/600x600bb.jpg",
                "2013", "Electronic", 10.0, 8.5, 9.5, 9.0, 9.5, 9.30,
                "Canlı enstrümanların elektronik prodüksiyonla kusursuz birleşimi. Miksaj ve mastering standardı belirleyen bir başyapıt."
            ),
            (
                "itunes_1440833098", "album", "Currents", "Tame Impala",
                "https://is1-ssl.mzstatic.com/image/thumb/Music115/v4/a6/2b/99/a62b99c4-3a9f-4c26-6624-e3b007b5c676/15UMGIM26179.rgb.jpg/600x600bb.jpg",
                "2015", "Alternative", 9.5, 9.0, 9.5, 8.5, 10.0, 9.30,
                "Kevin Parker'ın psikedelik synth-pop devrimi. Baştan sona tekrar tekrar dinlenebilirlik oranı en yüksek albümlerden."
            ),
            (
                "itunes_693387633", "album", "AM", "Arctic Monkeys",
                "https://is1-ssl.mzstatic.com/image/thumb/Music115/v4/7b/32/2b/7b322b71-25b2-08f5-9072-1827ff1b8085/887828031757.png/600x600bb.jpg",
                "2013", "Alternative", 9.0, 9.5, 9.5, 9.0, 9.5, 9.30,
                "Gece sürüşlerinin vazgeçilmez albümü. Alex Turner'ın söz yazarlığı ve bas-davul grooveları zamansız."
            ),
        ]

        for rel_id, rtype, title, artist, art, yr, genre, sp, sl, sm, sv, sr, ov, rev in sample_releases:
            cur.execute(
                """
                INSERT OR IGNORE INTO release_ratings (
                    user_id, username, release_id, release_type, release_title, artist_name,
                    artwork_url, release_year, genre,
                    score_production, score_lyrics, score_melody, score_vocals, score_replay,
                    overall_score, review_text, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (uid, "müzikgurusu", rel_id, rtype, title, artist, art, yr, genre, sp, sl, sm, sv, sr, ov, rev, now_iso),
            )
        conn.commit()
    except Exception as e:
        print(f"[db] seed error: {e}")
    finally:
        conn.close()


seed_initial_demo_data()


# ---------------------------------------------------------------------------
# Grammy 2025 Predictions & Favorites
# ---------------------------------------------------------------------------

def upsert_grammy_prediction(
    user_id: int,
    username: str,
    category_id: str,
    winner_pick: Optional[str] = None,
    favorite_pick: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Saves or updates a user's prediction (who will win) and/or favorite (who they want to win).
    Supports Supabase with SQLite fallback.
    """
    cfg = _get_supabase_config()
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Supabase Cloud attempt
    if cfg["url"] and cfg["key"]:
        try:
            lookup_url = (
                f"{cfg['url']}/rest/v1/grammy_predictions"
                f"?user_id=eq.{user_id}&category_id=eq.{category_id}&select=*"
            )
            l_resp = requests.get(lookup_url, headers=_supabase_headers(cfg["key"]), timeout=4)
            existing = l_resp.json()[0] if l_resp.status_code == 200 and l_resp.json() else {}

            payload = {
                "user_id": user_id,
                "username": username,
                "category_id": category_id,
                "winner_pick": winner_pick if winner_pick is not None else existing.get("winner_pick", ""),
                "favorite_pick": favorite_pick if favorite_pick is not None else existing.get("favorite_pick", ""),
                "updated_at": now_iso,
            }

            resp = requests.post(
                f"{cfg['url']}/rest/v1/grammy_predictions?on_conflict=user_id,category_id",
                headers=_supabase_headers(cfg["key"], prefer="resolution=merge-duplicates,return=representation"),
                json=payload,
                timeout=5,
            )
            if resp.status_code in (200, 201):
                return resp.json()[0] if resp.json() else payload
        except Exception as e:
            print(f"[db:supabase] upsert_grammy_prediction error, falling back to sqlite: {e}")

    # 2. SQLite Fallback
    conn = _get_sqlite_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT * FROM grammy_predictions WHERE user_id = ? AND category_id = ?",
            (user_id, category_id),
        )
        row = cur.fetchone()

        w_val = winner_pick if winner_pick is not None else (row["winner_pick"] if row else "")
        f_val = favorite_pick if favorite_pick is not None else (row["favorite_pick"] if row else "")

        if row:
            cur.execute(
                """
                UPDATE grammy_predictions
                SET winner_pick = ?, favorite_pick = ?, username = ?, updated_at = ?
                WHERE user_id = ? AND category_id = ?
                """,
                (w_val, f_val, username, now_iso, user_id, category_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO grammy_predictions (user_id, username, category_id, winner_pick, favorite_pick, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, username, category_id, w_val, f_val, now_iso),
            )
        conn.commit()
        return {
            "user_id": user_id,
            "username": username,
            "category_id": category_id,
            "winner_pick": w_val,
            "favorite_pick": f_val,
            "updated_at": now_iso,
        }
    except Exception as e:
        print(f"[db:sqlite] upsert_grammy_prediction error: {e}")
        return {}
    finally:
        conn.close()


def get_all_grammy_data(user_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Returns aggregation stats for all Grammy categories and the current user's picks.
    """
    cfg = _get_supabase_config()
    all_rows = []

    # 1. Supabase Cloud attempt
    if cfg["url"] and cfg["key"]:
        try:
            resp = requests.get(
                f"{cfg['url']}/rest/v1/grammy_predictions?select=*",
                headers=_supabase_headers(cfg["key"]),
                timeout=5,
            )
            if resp.status_code == 200:
                all_rows = resp.json()
        except Exception as e:
            print(f"[db:supabase] get_all_grammy_data error: {e}")

    # Fallback or local SQLite if empty / failed
    if not all_rows:
        try:
            conn = _get_sqlite_conn()
            cur = conn.cursor()
            cur.execute("SELECT * FROM grammy_predictions")
            all_rows = [dict(r) for r in cur.fetchall()]
            conn.close()
        except Exception as e:
            print(f"[db:sqlite] get_all_grammy_data error: {e}")

    user_picks: Dict[str, Dict[str, str]] = {}
    stats: Dict[str, Dict[str, Any]] = {}

    for row in all_rows:
        cid = row.get("category_id")
        if not cid:
            continue

        if cid not in stats:
            stats[cid] = {
                "total_winner_votes": 0,
                "total_favorite_votes": 0,
                "winner_counts": {},
                "favorite_counts": {},
                "winner_percentages": {},
                "favorite_percentages": {},
            }

        w = row.get("winner_pick") or ""
        f = row.get("favorite_pick") or ""
        uid = row.get("user_id")

        if user_id and uid == user_id:
            user_picks[cid] = {
                "winner": w,
                "favorite": f,
            }

        if w:
            stats[cid]["total_winner_votes"] += 1
            stats[cid]["winner_counts"][w] = stats[cid]["winner_counts"].get(w, 0) + 1

        if f:
            stats[cid]["total_favorite_votes"] += 1
            stats[cid]["favorite_counts"][f] = stats[cid]["favorite_counts"].get(f, 0) + 1

    # Calculate percentages
    for cid, cdata in stats.items():
        tot_w = cdata["total_winner_votes"]
        if tot_w > 0:
            for nid, count in cdata["winner_counts"].items():
                cdata["winner_percentages"][nid] = round((count / tot_w) * 100, 1)

        tot_f = cdata["total_favorite_votes"]
        if tot_f > 0:
            for nid, count in cdata["favorite_counts"].items():
                cdata["favorite_percentages"][nid] = round((count / tot_f) * 100, 1)

    return {
        "user_picks": user_picks,
        "stats": stats,
    }

