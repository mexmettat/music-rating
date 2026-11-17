document.addEventListener('DOMContentLoaded', () => {
    const SVG_PLAY = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>';
    const SVG_PAUSE = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>';

    // Apply dynamic data-bg, data-width, and data-disabled attributes cleanly
    document.querySelectorAll('[data-bg]').forEach(el => {
        if (el.dataset.bg) el.style.background = el.dataset.bg;
    });
    document.querySelectorAll('[data-width]').forEach(el => {
        if (el.dataset.width !== undefined) el.style.width = `${parseFloat(el.dataset.width) || 0}%`;
    });
    document.querySelectorAll('[data-disabled="true"]').forEach(el => {
        el.disabled = true;
        el.title = 'Puan vermek için giriş yapmalısınız';
    });

    // 1. Toast Notification Helper
    window.showToast = function (message, type = 'success') {
        const container = document.getElementById('toastContainer');
        if (!container) return;
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        if (type === 'error') {
            toast.style.borderColor = '#f43f5e';
        }
        container.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transition = 'opacity 0.25s ease';
            setTimeout(() => toast.remove(), 250);
        }, 3200);
    };

    // 2. Live Navbar Quick Search
    const searchInput = document.getElementById('globalSearchInput');
    const dropdown = document.getElementById('quickSearchDropdown');
    let searchTimer = null;

    if (searchInput && dropdown) {
        searchInput.addEventListener('input', () => {
            const q = searchInput.value.trim();
            clearTimeout(searchTimer);
            if (q.length < 2) {
                dropdown.classList.add('hidden');
                dropdown.innerHTML = '';
                return;
            }
            searchTimer = setTimeout(async () => {
                try {
                    const res = await fetch(`/api/quick-search?q=${encodeURIComponent(q)}`);
                    const data = await res.json();
                    const items = data.results || [];
                    if (!items.length) {
                        dropdown.classList.add('hidden');
                        return;
                    }
                    dropdown.innerHTML = items.map(it => `
                        <a href="/release/${it.release_id}" class="qs-item">
                            <img src="${it.artwork_url}" alt="${it.title}" class="qs-cover" />
                            <div class="qs-meta">
                                <div class="qs-title">${it.title}</div>
                                <div class="qs-sub">${it.artist} • ${it.release_type === 'single' ? 'SINGLE' : 'ALBÜM'} ${it.year ? '• ' + it.year : ''}</div>
                            </div>
                        </a>
                    `).join('');
                    dropdown.classList.remove('hidden');
                } catch (e) {
                    console.error(e);
                }
            }, 260);
        });

        document.addEventListener('click', (e) => {
            if (!searchInput.contains(e.target) && !dropdown.contains(e.target)) {
                dropdown.classList.add('hidden');
            }
        });
    }

    // 3. Sticky 30s Audio Preview Player
    const audioBar = document.getElementById('audioPlayerBar');
    const audioEl = document.getElementById('globalAudio');
    const playerArtwork = document.getElementById('playerArtwork');
    const playerTitle = document.getElementById('playerTitle');
    const playerArtist = document.getElementById('playerArtist');
    const playerToggleBtn = document.getElementById('playerToggleBtn');
    const playerToggleIcon = document.getElementById('playerToggleIcon');
    const playerSeek = document.getElementById('playerSeek');
    const playerCurrentTime = document.getElementById('playerCurrentTime');
    const playerDuration = document.getElementById('playerDuration');
    const playerCloseBtn = document.getElementById('playerCloseBtn');

    function formatSec(sec) {
        if (!sec || isNaN(sec)) return '0:00';
        const m = Math.floor(sec / 60);
        const s = Math.floor(sec % 60);
        return `${m}:${s < 10 ? '0' : ''}${s}`;
    }

    document.querySelectorAll('.play-preview-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const url = btn.dataset.url;
            if (!url || !audioEl) return;

            if (audioEl.src === url && !audioEl.paused) {
                audioEl.pause();
                return;
            }

            audioEl.src = url;
            playerArtwork.src = btn.dataset.artwork || '';
            playerTitle.textContent = btn.dataset.title || 'Önizleme';
            playerArtist.textContent = btn.dataset.artist || '';
            audioBar.classList.remove('hidden');
            audioEl.play();
        });
    });

    if (audioEl) {
        audioEl.addEventListener('play', () => {
            if (playerToggleIcon) playerToggleIcon.innerHTML = SVG_PAUSE;
        });
        audioEl.addEventListener('pause', () => {
            if (playerToggleIcon) playerToggleIcon.innerHTML = SVG_PLAY;
        });
        audioEl.addEventListener('timeupdate', () => {
            if (audioEl.duration) {
                playerSeek.value = (audioEl.currentTime / audioEl.duration) * 100;
                playerCurrentTime.textContent = formatSec(audioEl.currentTime);
                playerDuration.textContent = formatSec(audioEl.duration);
            }
        });
        playerToggleBtn?.addEventListener('click', () => {
            if (audioEl.paused) audioEl.play();
            else audioEl.pause();
        });
        playerSeek?.addEventListener('input', () => {
            if (audioEl.duration) {
                audioEl.currentTime = (playerSeek.value / 100) * audioEl.duration;
            }
        });
        playerCloseBtn?.addEventListener('click', () => {
            audioEl.pause();
            audioBar.classList.add('hidden');
        });
    }

    // 4. 5-Criteria Release Rating Sliders & Live Overall Score Calculation
    const sliders = document.querySelectorAll('.criteria-slider');
    const liveOverallEl = document.getElementById('liveOverallScore');

    function recalcOverall() {
        if (!sliders.length || !liveOverallEl) return;
        let sum = 0;
        sliders.forEach(sl => {
            const val = parseFloat(sl.value) || 0;
            sum += val;
            const targetId = sl.dataset.target;
            const badge = document.getElementById(targetId);
            if (badge) badge.textContent = val.toFixed(1);
        });
        const avg = sum / sliders.length;
        liveOverallEl.textContent = avg.toFixed(2);
    }

    sliders.forEach(sl => {
        sl.addEventListener('input', recalcOverall);
    });

    // Submit 5-Criteria Form via AJAX
    const releaseForm = document.getElementById('releaseRatingForm');
    if (releaseForm) {
        releaseForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const submitBtn = document.getElementById('submitReleaseRatingBtn');
            const fd = new FormData(releaseForm);
            const payload = Object.fromEntries(fd.entries());

            if (submitBtn) submitBtn.disabled = true;
            try {
                const res = await fetch('/api/rate/release', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    window.showToast(data.error || 'Puan kaydedilirken bir hata oluştu.', 'error');
                    if (data.auth_required) {
                        window.location.href = '/auth?mode=login';
                    }
                    return;
                }

                window.showToast(`5 kriterli puanınız kaydedildi! (Genel: ${data.overall_score.toFixed(2)}/10)`, 'success');

                // Update community stats live
                const st = data.stats;
                if (st) {
                    const commOverall = document.getElementById('communityOverallDisplay');
                    if (commOverall && st.avg_overall) commOverall.textContent = st.avg_overall.toFixed(2);
                    const voteCnt = document.getElementById('communityVoteCount');
                    if (voteCnt) voteCnt.textContent = `${st.count} değerlendirme`;

                    const keys = ['production', 'lyrics', 'melody', 'vocals', 'replay'];
                    keys.forEach(k => {
                        const v = st[`avg_${k}`];
                        const labelEl = document.getElementById(`comm_avg_${k}`);
                        const barEl = document.getElementById(`comm_bar_${k}`);
                        if (labelEl && v !== undefined) labelEl.textContent = `${v.toFixed(1)}/10`;
                        if (barEl && v !== undefined) barEl.style.width = `${v * 10}%`;
                    });
                }
            } catch (err) {
                console.error(err);
                window.showToast('Sunucu ile bağlantı kurulamadı.', 'error');
            } finally {
                if (submitBtn) submitBtn.disabled = false;
            }
        });
    }

    // 5. Track-by-Track 1-10 Quick Rating inside an Album
    document.querySelectorAll('.track-quick-rate').forEach(container => {
        const buttons = container.querySelectorAll('.ten-btn');
        buttons.forEach(btn => {
            btn.addEventListener('click', async () => {
                const score = parseFloat(btn.dataset.score);
                const payload = {
                    release_id: container.dataset.releaseId,
                    track_id: container.dataset.trackId,
                    track_number: parseInt(container.dataset.trackNumber || '1', 10),
                    track_title: container.dataset.trackTitle,
                    artist_name: container.dataset.artistName,
                    release_title: container.dataset.releaseTitle,
                    artwork_url: container.dataset.artworkUrl,
                    score: score,
                };

                buttons.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');

                try {
                    const res = await fetch('/api/rate/track', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                    });
                    const data = await res.json();
                    if (!res.ok || !data.ok) {
                        window.showToast(data.error || 'Şarkı puanlanamadı.', 'error');
                        return;
                    }

                    window.showToast(`"${payload.track_title}" -> ${score}/10 kaydedildi!`, 'success');

                    const trkAvgEl = document.getElementById(`trk_avg_${payload.track_id}`);
                    if (trkAvgEl) {
                        trkAvgEl.textContent = `${data.track_avg.toFixed(1)}/10 (${data.track_count} oy)`;
                    }
                    const albumTrkAvgEl = document.getElementById('albumTracksAvgDisplay');
                    if (albumTrkAvgEl && data.album_tracks_avg) {
                        albumTrkAvgEl.textContent = data.album_tracks_avg.toFixed(2);
                    }
                    const userTrkAvgEl = document.getElementById('userTracksAvgDisplay');
                    if (userTrkAvgEl && data.user_tracks_avg) {
                        userTrkAvgEl.textContent = data.user_tracks_avg.toFixed(2);
                    }
                } catch (err) {
                    console.error(err);
                    window.showToast('Şarkı puanı gönderilirken hata oluştu.', 'error');
                }
            });
        });
    });
});
