-- ============================================================================
-- SONORA MÜZİK PUANLAMA SİTESİ - SUPABASE VERİTABANI ŞEMASI
-- Bu SQL kodunu Supabase Dashboard -> SQL Editor kısmına yapıştırıp "Run" deyin.
-- ============================================================================

-- 1. KULLANICILAR TABLOSU
CREATE TABLE IF NOT EXISTS public.users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    bio TEXT DEFAULT '',
    avatar_color TEXT DEFAULT '#8b5cf6',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. ALBÜM VE SINGLE GENEL PUANLAMA TABLOSU (5 KRİTER + 10 ÜZERİNDEN ORTALAMA)
-- Kural: 5 kriter (Prodüksiyon, Sözler, Melodi, Vokal, Tekrar Dinlenebilirlik)
-- SADECE Albümün tamamı veya Single'lar için puanlanır.
CREATE TABLE IF NOT EXISTS public.release_ratings (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    username TEXT NOT NULL,
    release_id TEXT NOT NULL,           -- Örn: itunes_1440857781 veya spotify_xxx
    release_type TEXT NOT NULL,         -- 'album' veya 'single'
    release_title TEXT NOT NULL,
    artist_name TEXT NOT NULL,
    artwork_url TEXT DEFAULT '',
    release_year TEXT DEFAULT '',
    genre TEXT DEFAULT '',
    score_production NUMERIC(4,1) NOT NULL CHECK (score_production >= 1 AND score_production <= 10),
    score_lyrics NUMERIC(4,1) NOT NULL CHECK (score_lyrics >= 1 AND score_lyrics <= 10),
    score_melody NUMERIC(4,1) NOT NULL CHECK (score_melody >= 1 AND score_melody <= 10),
    score_vocals NUMERIC(4,1) NOT NULL CHECK (score_vocals >= 1 AND score_vocals <= 10),
    score_replay NUMERIC(4,1) NOT NULL CHECK (score_replay >= 1 AND score_replay <= 10),
    overall_score NUMERIC(4,2) NOT NULL CHECK (overall_score >= 1 AND overall_score <= 10),
    review_text TEXT DEFAULT '',
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, release_id)
);

-- 3. ALBÜM İÇİ TEKİL ŞARKI PUANLAMA TABLOSU (SADECE 10 ÜZERİNDEN PUAN)
-- Kural: Albümdeki şarkılara tek tek puan verirken 5 kriter istenmez,
-- sadece 10 üzerinden puan verilir.
CREATE TABLE IF NOT EXISTS public.track_ratings (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    username TEXT NOT NULL,
    release_id TEXT NOT NULL,           -- Ait olduğu albüm ID'si
    track_id TEXT NOT NULL,             -- Şarkı ID'si
    track_number INT DEFAULT 1,
    track_title TEXT NOT NULL,
    artist_name TEXT NOT NULL,
    release_title TEXT DEFAULT '',
    artwork_url TEXT DEFAULT '',
    score NUMERIC(4,1) NOT NULL CHECK (score >= 1 AND score <= 10),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, track_id)
);

-- Hızlı sorgular için indeksler
CREATE INDEX IF NOT EXISTS idx_release_ratings_release_id ON public.release_ratings(release_id);
CREATE INDEX IF NOT EXISTS idx_release_ratings_user_id ON public.release_ratings(user_id);
CREATE INDEX IF NOT EXISTS idx_track_ratings_release_id ON public.track_ratings(release_id);
CREATE INDEX IF NOT EXISTS idx_track_ratings_user_id ON public.track_ratings(user_id);

-- Row Level Security (RLS) - Flask API üzerinden erişim için açık izin politikaları
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.release_ratings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.track_ratings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public full access users" ON public.users;
CREATE POLICY "Public full access users" ON public.users FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Public full access release_ratings" ON public.release_ratings;
CREATE POLICY "Public full access release_ratings" ON public.release_ratings FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Public full access track_ratings" ON public.track_ratings;
CREATE POLICY "Public full access track_ratings" ON public.track_ratings FOR ALL USING (true) WITH CHECK (true);
