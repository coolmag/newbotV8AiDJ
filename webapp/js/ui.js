import { store, subscribe } from './store.js';
import { MENU_ROOT } from './genres.js';
import * as haptics from './haptics.js';

let menuStack = [];

function getEl(id) { return document.getElementById(id); }

function renderMenu() {
    const drawer = getEl('drawer-genres');
    if (!drawer) return;
    const current = menuStack.length > 0 ? menuStack[menuStack.length - 1] : { title: "Tape Collection", items: MENU_ROOT.children, isRoot: true };
    drawer.innerHTML = ''; 

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

    const listContainer = document.createElement('div');
    listContainer.className = 'scroll-area menu-list';
    current.items.forEach(item => {
        const row = document.createElement('div');
        row.className = 'menu-row';
        let iconHtml = '';
        if (item.action === 'random') iconHtml = '<span class="material-icons-round row-icon random">shuffle</span>';
        else if (item.children) iconHtml = '<span class="material-icons-round row-icon folder">folder</span>';
        else iconHtml = '<span class="material-icons-round row-icon music">album</span>';
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
                window.loadGenreHandler(item.action === 'random' ? "top 50 global hits" : item.query);
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
        container.innerHTML = '<div class="empty-state">No Tape Inserted</div>';
        return;
    }
    playlist.forEach((track, idx) => {
        const item = document.createElement('div');
        item.className = `playlist-row ${idx === currentIndex ? 'active' : ''}`;
        const iconType = idx === currentIndex ? 'graphic_eq' : 'audiotrack';
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
            const el = getEl('track-title-scrolling');
            if (el) el.textContent = `${track.artist} - ${track.title} *** `;
            const artistEl = getEl('track-artist');
            if (artistEl) artistEl.textContent = track.artist;
            
            if ('mediaSession' in navigator) {
                navigator.mediaSession.metadata = new MediaMetadata({ title: track.title, artist: track.artist });
            }
        }
        renderPlaylist(store.playlist, idx, player);
    });
    subscribe('playlist', (list) => renderPlaylist(list, store.currentTrackIndex, player));

    const audio = player.getAudioElement();
    audio.addEventListener('timeupdate', () => {
        if (!audio.duration) return;
        // Update tape counter format
        const curr = Math.floor(audio.currentTime);
        const el = getEl('time-current');
        if (el) el.textContent = curr.toString().padStart(4, '0');
    });

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
    
    // FX Button
    const btnFx = getEl('btn-fx');
    if(btnFx) {
        btnFx.onclick = () => {
            haptics.impact('medium');
            const isActive = player.toggleBassBoost();
            btnFx.style.background = isActive ? 'radial-gradient(circle, #00f2ff, #0099aa)' : '';
            btnFx.style.boxShadow = isActive ? '0 0 10px #00f2ff' : '';
        };
    }

    // Volume Slider (Knob logic simplified to slider)
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
        
        // Init pos
        volKnob.style.left = (audio.volume * 100) + '%';
        volKnob.style.transform = `translateX(-50%)`;
    }
}

export const UI = { initialize, toggleDrawer };