import { store, subscribe } from './store.js';
import { MENU_ROOT } from './genres.js';
import * as haptics from './haptics.js';

let menuStack = [];

function getEl(id) { return document.getElementById(id); }

// --- GLITCH ЭФФЕКТ ---
const GLITCH_CHARS = '!<>-_\/[]{}—=+*^?#________';
function glitchText(element, finalText) {
    if (!element) return;
    let iteration = 0;
    if (element.dataset.glitchInterval) clearInterval(parseInt(element.dataset.glitchInterval));
    
    const interval = setInterval(() => {
        element.textContent = finalText
            .split("")
            .map((letter, index) => {
                if (index < iteration) return finalText[index];
                return GLITCH_CHARS[Math.floor(Math.random() * GLITCH_CHARS.length)];
            })
            .join("");
        
        if (iteration >= finalText.length) { 
            clearInterval(interval);
            element.textContent = finalText;
        }
        iteration += 1 / 2;
    }, 30);
    element.dataset.glitchInterval = interval;
}

function getRandomQuery(node) {
    if (node.query) return node.query;
    if (node.children) {
        const child = node.children[Math.floor(Math.random() * node.children.length)];
        return getRandomQuery(child);
    }
    return "lofi hip hop";
}

// --- ОТРИСОВКА МЕНЮ ---
function renderMenu() {
    const drawer = getEl('drawer-genres');
    if (!drawer) return;
    
    const current = menuStack.length > 0 ? menuStack[menuStack.length - 1] : { title: "Frequency", items: MENU_ROOT.children, isRoot: true };

    drawer.innerHTML = ''; 

    // Header
    const header = document.createElement('div');
    header.className = 'drawer-header';

    const backBtn = document.createElement('button');
    backBtn.className = 'nav-btn';
    backBtn.innerHTML = '<span class="material-icons-round">arrow_back_ios_new</span>';
    backBtn.onclick = () => { 
        haptics.impact('light');
        if (!current.isRoot) { menuStack.pop(); renderMenu(); } 
    };
    backBtn.style.visibility = current.isRoot ? 'hidden' : 'visible';

    const title = document.createElement('div');
    title.className = 'drawer-title-text';
    title.textContent = current.title;

    const closeBtn = document.createElement('button');
    closeBtn.className = 'nav-btn';
    closeBtn.innerHTML = '<span class="material-icons-round">close</span>';
    closeBtn.onclick = () => toggleDrawer('genres', false);

    header.appendChild(backBtn); header.appendChild(title); header.appendChild(closeBtn);
    drawer.appendChild(header);

    // List
    const listContainer = document.createElement('div');
    listContainer.className = 'scroll-area menu-list';

    current.items.forEach(item => {
        const row = document.createElement('div');
        row.className = 'menu-row';
        
        let iconHtml = '';
        if (item.action === 'random') iconHtml = '<span class="material-icons-round row-icon random">shuffle</span>';
        else if (item.children) iconHtml = '<span class="material-icons-round row-icon folder">folder</span>';
        else iconHtml = '<span class="material-icons-round row-icon music">music_note</span>';

        const arrowHtml = item.children ? '<span class="material-icons-round row-arrow">chevron_right</span>' : '';

        row.innerHTML = `<div class="row-left">${iconHtml}<span class="row-title">${item.name}</span></div>${arrowHtml}`;
        
        row.onclick = () => {
            haptics.impact('light');
            row.classList.add('clicked');
            setTimeout(() => row.classList.remove('clicked'), 200);
            if (item.children) {
                menuStack.push({ title: item.name, items: item.children, isRoot: false });
                setTimeout(renderMenu, 50); 
            } else {
                toggleDrawer('genres', false);
                const q = item.action === 'random' ? getRandomQuery(MENU_ROOT) : item.query;
                window.loadGenreHandler(q);
            }
        };
        listContainer.appendChild(row);
    });
    drawer.appendChild(listContainer);
}

function renderPlaylist(playlist, currentIndex, player) {
    const container = getEl('playlist-container');
    if (!container) return;
    container.innerHTML = '';
    if (!playlist || playlist.length === 0) {
        container.innerHTML = '<div class="empty-state">Queue is empty</div>';
        return;
    }
    playlist.forEach((track, idx) => {
        const item = document.createElement('div');
        item.className = `playlist-row ${idx === currentIndex ? 'active' : ''}`;
        const iconType = idx === currentIndex ? 'equalizer' : 'music_note';
        
        item.innerHTML = `
            <div class="p-icon-box"><span class="material-icons-round">${iconType}</span></div>
            <div class="p-info">
                <div class="p-title">${track.title}</div>
                <div class="p-artist">${track.artist}</div>
            </div>
        `;
        
        item.onclick = () => { 
            haptics.impact('medium');
            player.playTrack(idx); 
            toggleDrawer('playlist', false); 
        };
        container.appendChild(item);
    });
    const activeEl = container.querySelector('.active');
    if (activeEl) activeEl.scrollIntoView({ block: 'center', behavior: 'smooth' });
}

function toggleDrawer(name, show) {
    const overlay = getEl('overlay');
    const dGenres = getEl('drawer-genres');
    const dPlaylist = getEl('drawer-playlist');
    
    if (show) {
        haptics.impact('medium');
        if(overlay) overlay.classList.add('active');
        if (name === 'genres') { 
            if(dGenres) dGenres.classList.add('active'); 
            if(dPlaylist) dPlaylist.classList.remove('active'); 
            if (menuStack.length === 0) renderMenu(); 
        }
        if (name === 'playlist') { 
            if(dPlaylist) dPlaylist.classList.add('active'); 
            if(dGenres) dGenres.classList.remove('active'); 
        }
    } else {
        if(overlay) overlay.classList.remove('active');
        if(dGenres) dGenres.classList.remove('active');
        if(dPlaylist) dPlaylist.classList.remove('active');
    }
}

function initialize(player) {
    subscribe('currentTrackIndex', (idx) => {
        const track = store.playlist[idx];
        if (track) {
            glitchText(getEl('track-title'), track.title);
            const ta = getEl('track-artist');
            if(ta) ta.textContent = track.artist;
            if ('mediaSession' in navigator) {
                navigator.mediaSession.metadata = new MediaMetadata({ title: track.title, artist: track.artist });
            }
        }
        renderPlaylist(store.playlist, idx, player);
    });

    subscribe('playlist', (list) => renderPlaylist(list, store.currentTrackIndex, player));

    // --- ОБЪЯВЛЕНИЕ ПЕРЕМЕННОЙ AUDIO (ОДИН РАЗ!) ---
    const audio = player.getAudioElement();

    audio.addEventListener('timeupdate', () => {
        if (!audio.duration) return;
        const pct = (audio.currentTime / audio.duration) * 100;
        const fill = getEl('progress-fill');
        const curr = getEl('time-current');
        const dur = getEl('time-duration');
        if (fill) fill.style.width = pct + '%';
        if (curr) curr.textContent = formatTime(audio.currentTime);
        if (dur) dur.textContent = formatTime(audio.duration);
    });
    
    const pContainer = document.querySelector('.progress-container');
    if(pContainer) {
        pContainer.onclick = (e) => {
            haptics.impact('light');
            const rect = pContainer.getBoundingClientRect();
            const p = (e.clientX - rect.left) / rect.width;
            player.seek(p);
        };
    }

    const bind = (id, fn) => { 
        const el = getEl(id); 
        if(el) el.onclick = () => {
            haptics.impact('light');
            fn();
        }; 
    };
    
    bind('btn-play-pause', () => player.togglePlay());
    bind('btn-next', () => player.nextTrack());
    bind('btn-prev', () => player.prevTrack());
    bind('btn-open-genres', () => toggleDrawer('genres', true));
    bind('btn-open-playlist', () => toggleDrawer('playlist', true));
    bind('overlay', () => toggleDrawer(null, false));
    
    const btnFx = getEl('btn-fx');
    if(btnFx) {
        btnFx.onclick = () => {
            haptics.impact('medium');
            const isActive = player.toggleBassBoost();
            btnFx.style.color = isActive ? '#00f2ff' : '#666';
            btnFx.style.textShadow = isActive ? '0 0 10px #00f2ff' : 'none';
        };
    }
    
    subscribe('isPlaying', (playing) => {
        const icon = document.querySelector('#btn-play-pause span');
        if(icon) icon.textContent = playing ? 'pause' : 'play_arrow';
    });

    // --- VOLUME LOGIC ---
    const volBg = getEl('vol-bg');
    const volFill = getEl('vol-fill');
    
    // Переменная audio уже объявлена выше, используем ее.
    // const audio = player.getAudioElement(); // Эту строку убираем!
    
    if (volBg && volFill) {
        if (localStorage.getItem('aurora_volume')) {
            audio.volume = parseFloat(localStorage.getItem('aurora_volume'));
        }
        volFill.style.width = (audio.volume * 100) + '%';

        const updateVolume = (e) => {
            const rect = volBg.getBoundingClientRect();
            let p = (e.clientX - rect.left) / rect.width;
            p = Math.max(0, Math.min(1, p));
            audio.volume = p;
            volFill.style.width = (p * 100) + '%';
            localStorage.setItem('aurora_volume', p);
        };

        let isVolDragging = false;
        volBg.addEventListener('mousedown', (e) => { isVolDragging = true; updateVolume(e); });
        volBg.addEventListener('touchstart', (e) => { isVolDragging = true; updateVolume(e.touches[0]); });
        
        document.addEventListener('mousemove', (e) => { if(isVolDragging) updateVolume(e); });
        document.addEventListener('touchmove', (e) => { if(isVolDragging) updateVolume(e.touches[0]); });
        
        document.addEventListener('mouseup', () => isVolDragging = false);
        document.addEventListener('touchend', () => isVolDragging = false);
    }
    
    const btnMute = getEl('icon-vol-mute');
    const btnMax = getEl('icon-vol-max');
    // Используем уже объявленную переменную audio
    if(btnMute) btnMute.onclick = () => { audio.volume = 0; volFill.style.width = '0%'; };
    if(btnMax) btnMax.onclick = () => { audio.volume = 1; volFill.style.width = '100%'; };
    
    subscribe('isPlaying', (playing) => {
        const icon = document.querySelector('#btn-play-pause span');
        if(icon) icon.textContent = playing ? 'pause' : 'play_arrow';
    });
}

function formatTime(s) {
    if(isNaN(s)) return '0:00';
    const m = Math.floor(s/60);
    const sec = Math.floor(s%60);
    return `${m}:${sec.toString().padStart(2,'0')}`;
}

export const UI = { initialize, toggleDrawer };