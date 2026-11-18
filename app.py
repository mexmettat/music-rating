import os
from functools import wraps
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
)
from dotenv import load_dotenv
from services.music_api import (
    search_catalog,
    get_curated_catalog,
    get_release_details,
    CURATED_CATEGORIES,
)
from services.db import (
    create_user,
    authenticate_user,
    upsert_release_rating,
    get_release_ratings_data,
    upsert_track_rating,
    get_album_track_ratings_summary,
    get_recent_reviews,
    get_community_rated_releases,
    get_top_rated_releases,
    get_bulk_release_stats,
    get_user_profile_stats,
    upsert_grammy_prediction,
    get_all_grammy_data,
)
from services.grammy_data import GRAMMY_CATEGORIES

load_dotenv(override=True)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "sonora-super-secret-key-2026")

CRITERIA_META = [
    {"key": "production", "field": "score_production", "label": "Prodüksiyon & Miksaj", "icon": "sliders", "desc": "Ses kalitesi, aranje derinliği, miks ve mastering dengesi"},
    {"key": "lyrics", "field": "score_lyrics", "label": "Sözler & Tema", "icon": "feather", "desc": "Hikaye anlatımı, lirik derinlik ve kavramsal bütünlük"},
    {"key": "melody", "field": "score_melody", "label": "Melodi & Beste", "icon": "music", "desc": "Müzikal kompozisyon, akor yürüyüşleri ve akılda kalıcılık"},
    {"key": "vocals", "field": "score_vocals", "label": "Vokal / İcra", "icon": "mic", "desc": "Vokal performansı, duygu aktarımı ve enstrüman hakimiyeti"},
    {"key": "replay", "field": "score_replay", "label": "Tekrar Dinlenebilirlik", "icon": "repeat", "desc": "Sıkılmadan tekrar dinleme isteği ve zamansızlık etkisi"},
]


@app.context_processor
def inject_globals():
    user = session.get("user")
    return {
        "current_user": user,
        "criteria_meta": CRITERIA_META,
        "curated_categories": CURATED_CATEGORIES,
    }


def login_required_json(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return jsonify({"ok": False, "error": "Puan vermek için önce giriş yapmalısınız.", "auth_required": True}), 401
        return f(*args, **kwargs)
    return decorated


@app.route("/")
def index():
    sort_by = request.args.get("sort", "newest")
    if sort_by not in ("newest", "score_desc", "score_asc", "most_reviewed"):
        sort_by = "newest"

    genre_filter = (request.args.get("genre") or "all").strip()
    rtype_filter = (request.args.get("rtype") or "all").strip()
    if rtype_filter not in ("all", "album", "single"):
        rtype_filter = "all"

    community_data = get_community_rated_releases(
        sort_by=sort_by,
        genre_filter=genre_filter,
        rtype_filter=rtype_filter,
    )

    top_releases = get_top_rated_releases(limit=6)
    recent_reviews = get_recent_reviews(limit=6)

    return render_template(
        "index.html",
        rated_items=community_data["items"],
        available_genres=community_data["genres"],
        total_rated_count=community_data["total_count"],
        active_sort=sort_by,
        active_genre=genre_filter,
        active_rtype=rtype_filter,
        top_releases=top_releases,
        recent_reviews=recent_reviews,
    )


@app.route("/search")
def search():
    q = (request.args.get("q") or "").strip()
    filter_type = request.args.get("type", "all")
    if filter_type not in ("all", "album", "single"):
        filter_type = "all"

    results = []
    if q:
        results = search_catalog(q, filter_type=filter_type, limit=28)
        rel_ids = [r["release_id"] for r in results]
        stats_map = get_bulk_release_stats(rel_ids)
        for r in results:
            st = stats_map.get(r["release_id"])
            r["community_score"] = st["avg"] if st else None
            r["community_count"] = st["count"] if st else 0

    return render_template(
        "search.html",
        query=q,
        filter_type=filter_type,
        results=results,
    )


@app.route("/api/quick-search")
def api_quick_search():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"results": []})
    results = search_catalog(q, filter_type="all", limit=8)
    return jsonify({"results": results})


@app.route("/release/<release_id>")
def release_detail(release_id: str):
    release = get_release_details(release_id)
    if not release:
        flash("Aradığınız albüm veya single katalogda bulunamadı.", "error")
        return redirect(url_for("index"))

    user = session.get("user")
    uid = user["id"] if user else None

    ratings_data = get_release_ratings_data(release_id, current_user_id=uid)
    track_summary = get_album_track_ratings_summary(release_id, current_user_id=uid)

    return render_template(
        "release.html",
        release=release,
        ratings_data=ratings_data,
        track_summary=track_summary,
    )


@app.route("/api/rate/release", methods=["POST"])
@login_required_json
def api_rate_release():
    """
    Saves a 5-Criteria rating for an Album (as a whole) or a Single.
    """
    data = request.get_json(silent=True) or {}
    user = session["user"]

    release_id = (data.get("release_id") or "").strip()
    release_type = (data.get("release_type") or "album").strip()
    if release_type not in ("album", "single"):
        return jsonify({"ok": False, "error": "5 kriterli puanlama yalnızca Albüm geneli veya Single için kullanılabilir."}), 400

    try:
        sp = float(data.get("score_production", 0))
        sl = float(data.get("score_lyrics", 0))
        sm = float(data.get("score_melody", 0))
        sv = float(data.get("score_vocals", 0))
        sr = float(data.get("score_replay", 0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Lütfen 5 kriterin tamamı için 1 ile 10 arasında geçerli bir puan girin."}), 400

    res = upsert_release_rating(
        user_id=user["id"],
        username=user["username"],
        release_id=release_id,
        release_type=release_type,
        release_title=data.get("release_title", "Bilinmeyen Yapım"),
        artist_name=data.get("artist_name", "Bilinmeyen Sanatçı"),
        artwork_url=data.get("artwork_url", ""),
        release_year=data.get("release_year", ""),
        genre=data.get("genre", ""),
        score_production=sp,
        score_lyrics=sl,
        score_melody=sm,
        score_vocals=sv,
        score_replay=sr,
        review_text=data.get("review_text", ""),
    )

    if not res.get("ok"):
        return jsonify(res), 400

    updated_stats = get_release_ratings_data(release_id, current_user_id=user["id"])
    return jsonify({
        "ok": True,
        "message": "5 kriterli değerlendirmeniz kaydedildi!",
        "overall_score": res["overall_score"],
        "stats": {
            "count": updated_stats["count"],
            "avg_overall": updated_stats["avg_overall"],
            "avg_production": updated_stats["avg_production"],
            "avg_lyrics": updated_stats["avg_lyrics"],
            "avg_melody": updated_stats["avg_melody"],
            "avg_vocals": updated_stats["avg_vocals"],
            "avg_replay": updated_stats["avg_replay"],
        },
    })


@app.route("/api/rate/track", methods=["POST"])
@login_required_json
def api_rate_track():
    """
    Saves a single 1-10 score for an individual song inside an Album.
    (No 5 criteria required for album sub-tracks!)
    """
    data = request.get_json(silent=True) or {}
    user = session["user"]

    release_id = (data.get("release_id") or "").strip()
    track_id = (data.get("track_id") or "").strip()
    if not release_id or not track_id:
        return jsonify({"ok": False, "error": "Eksik albüm veya şarkı bilgisi."}), 400

    try:
        score = float(data.get("score", 0))
        if score < 1 or score > 10:
            raise ValueError()
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Şarkı puanı 1 ile 10 arasında olmalıdır."}), 400

    res = upsert_track_rating(
        user_id=user["id"],
        username=user["username"],
        release_id=release_id,
        track_id=track_id,
        track_number=int(data.get("track_number", 1)),
        track_title=data.get("track_title", "Şarkı"),
        artist_name=data.get("artist_name", ""),
        release_title=data.get("release_title", ""),
        artwork_url=data.get("artwork_url", ""),
        score=score,
    )

    if not res.get("ok"):
        return jsonify(res), 400

    summary = get_album_track_ratings_summary(release_id, current_user_id=user["id"])
    track_stat = summary["track_stats"].get(track_id, {"avg": score, "count": 1})

    return jsonify({
        "ok": True,
        "track_id": track_id,
        "user_score": res["score"],
        "track_avg": track_stat["avg"],
        "track_count": track_stat["count"],
        "album_tracks_avg": summary["album_tracks_avg"],
        "user_tracks_avg": summary["user_tracks_avg"],
    })


@app.route("/leaderboard")
def leaderboard():
    top_releases = get_top_rated_releases(limit=30)
    return render_template("leaderboard.html", top_releases=top_releases)


@app.route("/auth", methods=["GET"])
def auth_page():
    if "user" in session:
        return redirect(url_for("profile", username=session["user"]["username"]))
    mode = request.args.get("mode", "login")
    return render_template("auth.html", mode=mode)


@app.route("/login", methods=["POST"])
def login_post():
    identifier = (request.form.get("identifier") or "").strip()
    password = request.form.get("password") or ""
    next_url = request.form.get("next") or url_for("index")

    if not identifier or not password:
        flash("Lütfen kullanıcı adı/e-posta ve şifrenizi girin.", "error")
        return redirect(url_for("auth_page", mode="login"))

    res = authenticate_user(identifier, password)
    if not res["ok"]:
        flash(res["error"], "error")
        return redirect(url_for("auth_page", mode="login"))

    u = res["user"]
    session["user"] = {
        "id": u["id"],
        "username": u["username"],
        "email": u["email"],
        "avatar_color": u.get("avatar_color", "#E84A27"),
    }
    flash(f"Tekrar hoş geldin, {u['username']}!", "success")
    return redirect(next_url)


@app.route("/register", methods=["POST"])
def register_post():
    username = (request.form.get("username") or "").strip()
    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""
    bio = (request.form.get("bio") or "").strip()

    if len(username) < 3:
        flash("Kullanıcı adı en az 3 karakter olmalıdır.", "error")
        return redirect(url_for("auth_page", mode="register"))
    if "@" not in email:
        flash("Lütfen geçerli bir e-posta adresi girin.", "error")
        return redirect(url_for("auth_page", mode="register"))
    if len(password) < 5:
        flash("Şifre en az 5 karakter olmalıdır.", "error")
        return redirect(url_for("auth_page", mode="register"))

    res = create_user(username, email, password, bio)
    if not res["ok"]:
        flash(res["error"], "error")
        return redirect(url_for("auth_page", mode="register"))

    u = res["user"]
    session["user"] = {
        "id": u["id"],
        "username": u["username"],
        "email": u["email"],
        "avatar_color": u.get("avatar_color", "#E84A27"),
    }
    flash("Hesabınız başarıyla oluşturuldu! Hemen albüm ve single puanlamaya başlayabilirsiniz.", "success")
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Başarıyla çıkış yapıldı.", "info")
    return redirect(url_for("index"))


@app.route("/profile/<username>")
def profile(username: str):
    pdata = get_user_profile_stats(username)
    if not pdata:
        flash("Kullanıcı bulunamadı.", "error")
        return redirect(url_for("index"))
    return render_template("profile.html", profile=pdata)


@app.route("/grammy")
def grammy_hub():
    current_user = session.get("user")
    uid = current_user["id"] if current_user else None
    grammy_data = get_all_grammy_data(uid)
    return render_template(
        "grammy.html",
        categories=GRAMMY_CATEGORIES,
        user_picks=grammy_data.get("user_picks", {}),
        stats=grammy_data.get("stats", {}),
    )


@app.route("/api/grammy/predict", methods=["POST"])
@login_required_json
def api_grammy_predict():
    current_user = session.get("user")
    data = request.get_json(silent=True) or {}
    category_id = (data.get("category_id") or "").strip()
    pick_type = (data.get("pick_type") or "").strip()
    nominee_id = (data.get("nominee_id") or "").strip()

    if not category_id or pick_type not in ("winner", "favorite") or not nominee_id:
        return jsonify({"ok": False, "error": "Geçersiz kategori veya seçim parametresi."}), 400

    winner_pick = nominee_id if pick_type == "winner" else None
    favorite_pick = nominee_id if pick_type == "favorite" else None

    upsert_grammy_prediction(
        user_id=current_user["id"],
        username=current_user["username"],
        category_id=category_id,
        winner_pick=winner_pick,
        favorite_pick=favorite_pick,
    )

    g_data = get_all_grammy_data(current_user["id"])
    cat_stats = g_data.get("stats", {}).get(category_id, {})
    user_cat_picks = g_data.get("user_picks", {}).get(category_id, {})

    return jsonify({
        "ok": True,
        "category_id": category_id,
        "pick_type": pick_type,
        "user_picks": user_cat_picks,
        "stats": cat_stats,
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True, reloader_type="stat")
