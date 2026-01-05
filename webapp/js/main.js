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
        // Логгер убран из UI, но оставим в консоли для дебага
        console.log(`[SYS] ${msg}`);
        const logLed = document.getElementById('system-log');
        if (logLed) {
            logLed.textContent = msg;
            logLed.style.color = type === 'error' ? '#f00' : '#0f0';
        }
    }
};

document.addEventListener('DOMContentLoaded', () => {
    logger.init();
    
    // SAFE TELEGRAM INIT
    try {
        const tg = window.Telegram?.WebApp;
        if (tg) { 
            tg.expand(); 
            // Проверка версии перед вызовом новых методов
            if (tg.isVersionAtLeast && tg.isVersionAtLeast('6.1')) {
                tg.setHeaderColor('#0a0a0f'); 
                tg.setBackgroundColor('#0a0a0f'); 
            }
        }
    } catch (e) { console.warn("TG Init Error:", e); }

    Player.setStatusCallback((state, message) => {
        logger.print(message, state === 'error' ? 'error' : 'info');
        const tArtist = document.getElementById('track-artist');
        if (tArtist) {
            if (state === 'loading') { tArtist.textContent = "LOADING..."; tArtist.style.color = '#ffe600'; } 
            else if (state === 'playing') {
                const track = store.playlist[store.currentTrackIndex];
                if (track) { tArtist.textContent = track.artist; tArtist.style.color = '#333'; }
            }
        }
    });

    const startBtn = document.getElementById('btn-start-system');
    const startOverlay = document.getElementById('start-overlay');
    
    const handleStart = async (e) => {
        if (e && e.cancelable) e.preventDefault();
        const audio = Player.getAudioElement();
        try {
            // Тихая инициализация аудио контекста
            if (audio.paused) {
                await audio.play().then(() => { audio.pause(); audio.currentTime = 0; }).catch(() => {});
            }
        } catch (e) {}
        
        if (startOverlay) { 
            startOverlay.style.opacity = '0'; 
            setTimeout(() => startOverlay.remove(), 500); 
        }
        
        try { await Visualizer.initialize(audio); } catch (e) {}
        window.loadGenreHandler('top 50 global hits');
    };
    
    if (startBtn) {
        startBtn.addEventListener('click', handleStart);
        startBtn.addEventListener('touchstart', handleStart, { passive: false });
    }

    window.loadGenreHandler = async (query) => {
        // Закрываем меню, если открыто
        const genreDrawer = document.getElementById('drawer-genres');
        if (genreDrawer) genreDrawer.classList.remove('active');
        const overlay = document.getElementById('overlay');
        if (overlay) overlay.classList.remove('active');

        logger.print(`SCANNING: ${query.toUpperCase()}`);
        const tTitle = document.getElementById('track-title-scrolling');
        if(tTitle) tTitle.textContent = "SEARCHING TAPE...";
        
        try {
            const playlist = await fetchPlaylist(query);
            store.playlist = playlist;
            if (playlist && playlist.length > 0) { 
                logger.print(`FOUND ${playlist.length} TRACKS`); 
                Player.playTrack(0); 
            } else { 
                logger.print('NO TAPE FOUND', 'error'); 
                if(tTitle) tTitle.textContent = "EMPTY DECK"; 
            }
        } catch (err) { 
            logger.print('NET ERROR', 'error'); 
        }
    };

    const btnShuffle = document.getElementById('btn-shuffle');
    if (btnShuffle) {
        btnShuffle.onclick = () => {
            if (!store.playlist || store.playlist.length < 2) return;
            // Fisher-Yates shuffle
            for (let i = store.playlist.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [store.playlist[i], store.playlist[j]] = [store.playlist[j], store.playlist[i]];
            }
            store.currentTrackIndex = -1;
            Player.playTrack(0);
        };
    }

    // AI Logic
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
        
        const tTitle = document.getElementById('track-title-scrolling');
        if(tTitle) tTitle.textContent = "NEURAL PROCESSING...";
        
        const playlist = await AI.askAurora(prompt);
        if (playlist && playlist.length > 0) { 
            store.playlist = playlist; 
            Player.playTrack(0); 
        }
    };

    UI.initialize(Player);
});