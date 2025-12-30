import { store } from './store.js';
import { fetchPlaylist } from './api.js';
import { Player } from './player.js';
import { Visualizer } from './visualizer.js';
import { UI } from './ui.js';
import * as AI from './ai.js';

const logger = {
    el: null,
    init() { this.el = document.getElementById('system-log'); },
    print(msg, type = 'info') {
        if (!this.el) this.el = document.getElementById('system-log');
        if (!this.el) return;
        this.el.textContent = `> ${msg}`;
        this.el.className = 'system-log';
        if (type === 'error') this.el.classList.add('log-error');
        if (type === 'success') this.el.classList.add('log-success');
        if (type === 'loading') this.el.classList.add('log-loading');
    }
};

window.onerror = function(msg) { if(logger && logger.print) logger.print('ERR: ' + msg, 'error'); return false; };

document.addEventListener('DOMContentLoaded', () => {
    logger.init();
    try {
        const tg = window.Telegram?.WebApp;
        if (tg) { tg.expand(); tg.setHeaderColor('#050510'); tg.setBackgroundColor('#050510'); }
    } catch (e) { console.warn(e); }

    Player.setStatusCallback((state, message) => {
        let logType = 'info';
        if (state === 'error') logType = 'error';
        if (state === 'playing') logType = 'success';
        if (state === 'loading') logType = 'loading';
        logger.print(message, logType);
        const tArtist = document.getElementById('track-artist');
        if (tArtist) {
            if (state === 'loading') { tArtist.textContent = "Processing..."; tArtist.style.color = '#ffe600'; } 
            else if (state === 'playing') {
                const track = store.playlist[store.currentTrackIndex];
                if (track) { tArtist.textContent = track.artist; tArtist.style.color = '#8899a6'; }
            }
        }
    });

    const startBtn = document.getElementById('btn-start-system');
    const startOverlay = document.getElementById('start-overlay');
    const handleStart = async (e) => {
        if (e && e.cancelable) e.preventDefault();
        const audio = Player.getAudioElement();
        try {
            if (audio.paused) {
                audio.play().then(() => { audio.pause(); audio.currentTime = 0; }).catch(err => console.log("Audio unlock:", err));
            }
        } catch (e) {}
        logger.print('SYSTEM STARTUP...', 'loading');
        if (startOverlay) { startOverlay.style.opacity = '0'; setTimeout(() => startOverlay.remove(), 500); }
        try { await Visualizer.initialize(audio); logger.print('AUDIO CORE ONLINE', 'success'); } catch (e) { logger.print('INIT FAIL: ' + e.message, 'error'); }
        window.loadGenreHandler('lofi hip hop radio');
    };
    if (startBtn) {
        startBtn.addEventListener('click', handleStart);
        startBtn.addEventListener('touchstart', handleStart, { passive: false });
    }

    window.loadGenreHandler = async (query) => {
        UI.toggleDrawer('genres', false);
        logger.print(`SEARCHING: ${query.toUpperCase()}`, 'loading');
        const tTitle = document.getElementById('track-title');
        const tArtist = document.getElementById('track-artist');
        if(tTitle) tTitle.textContent = "Scanning...";
        if(tArtist) tArtist.textContent = "Please wait...";
        try {
            const playlist = await fetchPlaylist(query);
            store.playlist = playlist;
            if (playlist && playlist.length > 0) { logger.print(`FOUND ${playlist.length} TRACKS`, 'success'); Player.playTrack(0); } 
            else { logger.print('NO SIGNALS FOUND', 'error'); if(tTitle) tTitle.textContent = "Empty"; }
        } catch (err) { logger.print('NET ERROR', 'error'); if(tTitle) tTitle.textContent = "Connection Fail"; }
    };

    const btnShuffle = document.getElementById('btn-shuffle');
    if (btnShuffle) {
        btnShuffle.onclick = () => {
            if (!store.playlist || store.playlist.length < 2) return;
            logger.print('SHUFFLING...', 'loading');
            for (let i = store.playlist.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [store.playlist[i], store.playlist[j]] = [store.playlist[j], store.playlist[i]];
            }
            store.currentTrackIndex = -1;
            Player.playTrack(0);
        };
    }

    const aiBtn = document.getElementById('btn-ai');
    const aiModal = document.getElementById('ai-modal');
    const aiInput = document.getElementById('ai-input');
    const aiSend = document.getElementById('btn-ai-send');
    const aiCancel = document.getElementById('btn-ai-cancel');
    if (aiBtn) aiBtn.onclick = () => { aiModal.classList.add('active'); aiInput.focus(); };
    if (aiCancel) aiCancel.onclick = () => aiModal.classList.remove('active');
    if (aiSend) aiSend.onclick = async () => {
        const prompt = aiInput.value;
        if (!prompt) return;
        aiModal.classList.remove('active');
        aiInput.value = '';
        document.getElementById('track-title').textContent = "NEURAL PROCESSING...";
        document.documentElement.style.setProperty('--reactor-color', '#bc13fe');
        const playlist = await AI.askAurora(prompt);
        if (playlist && playlist.length > 0) { store.playlist = playlist; Player.playTrack(0); }
    };

    UI.initialize(Player);
});