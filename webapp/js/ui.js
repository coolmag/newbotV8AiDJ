import { store, subscribe } from './store.js';
import { MENU_ROOT } from './genres.js';
import * as haptics from './haptics.js';

let menuStack = [];
function getEl(id) { return document.getElementById(id); }

function renderMenu() {
    const drawer = getEl('genre-grid');
    if (!drawer) return;
    const current = menuStack.length > 0 ? menuStack[menuStack.length - 1] : { title: "Library", items: MENU_ROOT.children, isRoot: true };
    drawer.innerHTML = ''; 
    
    // Back button
    if (!current.isRoot) {
        const backRow = document.createElement('div');
        backRow.className = 'menu-row';
        backRow.innerHTML = `
            <div class="icon-box"><span class="material-icons-round">arrow_back</span></div>
            <div class="p-info"><div class="p-title">BACK</div></div>
        `;
        backRow.onclick = () => { haptics.impact('light'); menuStack.pop(); renderMenu(); };
        drawer.appendChild(backRow);
    }

    current.items.forEach(item => {
        const row = document.createElement('div');
        row.className = 'menu-row';
        
        let icon = 'album';
        if (item.children) icon = 'folder';
        if (item.action === 'random') icon = 'shuffle';
        
        row.innerHTML = `
            <div class="icon-box"><span class="material-icons-round">${icon}</span></div>
            <div class="p-info">
                <div class="p-title">${item.name}</div>
            </div>
            ${item.children ? '<span class="material-icons-round" style="color:#666">chevron_right</span>' : ''}
        `;
        
        row.onclick = () => {
            haptics.impact('light');
            if (item.children) {
                menuStack.push({ title: item.name, items: item.children, isRoot: false });
                renderMenu();
            } else {
                toggleDrawer('genres', false);
                window.loadGenreHandler(item.action === 'random' ? "top 50 global hits" : item.query);
            }
        };
        drawer.appendChild(row);
    });
}

function renderPlaylist(playlist, currentIndex, player) {
    const container = getEl('playlist-container');
    if (!container) return;
    container.innerHTML = '';
    
    if (!playlist || playlist.length === 0) {
        container.innerHTML = '<div style="text-align:center; color:#555; margin-top:50px;">NO TAPE LOADED</div>';
        return;
    }
    
    playlist.forEach((track, idx) => {
        const item = document.createElement('div');
        item.className = `playlist-row ${idx === currentIndex ? 'active' : ''}`;
        
        const iconType = idx === currentIndex ? 'graphic_eq' : 'music_note';
        
        item.innerHTML = `
            <div class="icon-box"><span class="material-icons-round" style="${idx===currentIndex?'color:var(--primary-neon)':''}">${iconType}</span></div>
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
    
    // Reset classes
    if (overlay) overlay.classList.remove('active');
    if (dGenres) dGenres.classList.remove('active');
    if (dPlaylist) dPlaylist.classList.remove('active');
    
    if (show) {
        haptics.impact('medium');
        if (overlay) overlay.classList.add('active');
        
        if (name === 'genres') {
            if (dGenres) dGenres.classList.add('active');
            if (menuStack.length === 0) renderMenu();
        } else if (name === 'playlist') {
            if (dPlaylist) dPlaylist.classList.add('active');
        }
    }
}

function initialize(player) {
    subscribe('currentTrackIndex', (idx) => {
        const track = store.playlist[idx];
        if (track) {
            const el = getEl('track-title-scrolling');
            if (el) el.textContent = `${track.artist} - ${track.title} *** `;
            const artistEl = getEl('track-artist');
            if (artistEl) artistEl.textContent = track.artist;
        }
        renderPlaylist(store.playlist, idx, player);
    });
    subscribe('playlist', (list) => renderPlaylist(list, store.currentTrackIndex, player));

    const audio = player.getAudioElement();
    const seekBar = getEl('seek-bar');
    const seekFill = getEl('seek-fill');
    const counter = getEl('time-current');
    
    audio.addEventListener('timeupdate', () => {
        if (!audio.duration) return;
        const pct = (audio.currentTime / audio.duration) * 100;
        if (seekFill) seekFill.style.width = pct + '%';
        if (counter) counter.textContent = Math.floor(audio.currentTime).toString().padStart(4, '0');
    });
    
    if (seekBar) {
        seekBar.onclick = (e) => {
            const rect = seekBar.getBoundingClientRect();
            const p = (e.clientX - rect.left) / rect.width;
            player.seek(p);
        };
    }

    const bind = (id, fn) => { 
        const el = getEl(id); 
        if(el) el.onclick = () => { haptics.impact('light'); fn(); }; 
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
            btnFx.style.background = isActive ? '#aaa' : '#e0e0e0';
            const span = btnFx.querySelector('span');
            if(span) span.style.color = isActive ? 'var(--primary-neon)' : '#444';
        };
    }

    // Volume
    const volBg = getEl('vol-bg');
    const volKnob = getEl('vol-knob');
    if (volBg && volKnob) {
        const updateVolume = (e) => {
            const rect = volBg.getBoundingClientRect();
            let p = (e.clientX - rect.left) / rect.width;
            p = Math.max(0, Math.min(1, p));
            audio.volume = p;
            volKnob.style.left = (p * 100) + '%';
            volKnob.style.transform = `translateX(-50%)`;
        };
        let isVolDragging = false;
        volBg.addEventListener('mousedown', (e) => { isVolDragging = true; updateVolume(e); });
        volBg.addEventListener('touchstart', (e) => { isVolDragging = true; updateVolume(e.touches[0]); });
        document.addEventListener('mousemove', (e) => { if(isVolDragging) updateVolume(e); });
        document.addEventListener('touchmove', (e) => { if(isVolDragging) updateVolume(e.touches[0]); });
        document.addEventListener('mouseup', () => isVolDragging = false);
        document.addEventListener('touchend', () => isVolDragging = false);
        
        volKnob.style.left = (audio.volume * 100) + '%';
        volKnob.style.transform = `translateX(-50%)`;
    }
}

export const UI = { initialize, toggleDrawer };