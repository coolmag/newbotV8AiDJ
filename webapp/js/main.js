import { store } from './store.js';
import { fetchPlaylist } from './api.js';
import { Player } from './player.js';
import { Visualizer } from './visualizer.js';
import { UI } from './ui.js';
import * as AI from './ai.js'; // Импорт нового модуля

// --- SYSTEM LOGGER ---
const logger = {
    el: null,
    init() {
        this.el = document.getElementById('system-log');
    },
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

window.onerror = function(msg) {
    if(logger && logger.print) logger.print('ERR: ' + msg, 'error');
    return false;
};

document.addEventListener('DOMContentLoaded', () => {
    logger.init();
    
    // 1. Telegram
    try {
        const tg = window.Telegram?.WebApp;
        if (tg) {
            tg.expand();
            if (tg.isVersionAtLeast('6.1')) {
                tg.setHeaderColor('#050510');
                tg.setBackgroundColor('#050510');
            }
        }
    } catch (e) {
        console.warn(e);
    }

    // 2. Logs
    Player.setStatusCallback((state, message) => {
        let logType = 'info';
        if (state === 'error') logType = 'error';
        if (state === 'playing') logType = 'success';
        if (state === 'loading') logType = 'loading';
        logger.print(message, logType);

        const tArtist = document.getElementById('track-artist');
        if (tArtist) {
            if (state === 'loading') {
                tArtist.textContent = "Processing...";
                tArtist.style.color = '#ffe600';
            } else if (state === 'playing') {
                const track = store.playlist[store.currentTrackIndex];
                if (track) {
                    tArtist.textContent = track.artist;
                    tArtist.style.color = '#8899a6';
                }
            }
        }
    });

    // 3. Start Button (Mobile Optimized)
    const startBtn = document.getElementById('btn-start-system');
    const startOverlay = document.getElementById('start-overlay');

    const handleStart = async (e) => {
        // Предотвращаем двойное срабатывание (и touch и click)
        if (e && e.cancelable) e.preventDefault();
        
        // --- AUDIO UNLOCK FOR MOBILE ---
        // Важно: создать или возобновить контекст СРАЗУ по клику
        const audio = Player.getAudioElement();
        try {
            // Пытаемся проиграть тишину, чтобы iOS разблокировал звук
            if (audio.paused) {
                audio.play().then(() => {
                    audio.pause();
                    audio.currentTime = 0;
                }).catch(err => console.log("Audio unlock interaction:", err));
            }
        } catch (e) { console.warn("Audio unlock failed", e); }
        // -------------------------------

        logger.print('SYSTEM STARTUP...', 'loading');
        
        if (startOverlay) {
            startOverlay.style.opacity = '0';
            setTimeout(() => startOverlay.remove(), 500);
        }

        try {
            await Visualizer.initialize(audio);
            logger.print('AUDIO CORE ONLINE', 'success');
        } catch (e) {
            logger.print('AUDIO INIT FAIL: ' + e.message, 'error');
        }
        
        // Запускаем музыку
        window.loadGenreHandler('lofi hip hop radio');
    };

    if (startBtn) {
        // Вешаем и клик, и тач - для надежности на всех устройствах
        startBtn.addEventListener('click', handleStart);
        startBtn.addEventListener('touchstart', handleStart, { passive: false });
    }

    // 4. Load Genre
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
            
            if (playlist && playlist.length > 0) {
                logger.print(`FOUND ${playlist.length} TRACKS`, 'success');
                Player.playTrack(0);
            } else {
                logger.print('NO SIGNALS FOUND', 'error');
                if(tTitle) tTitle.textContent = "Empty";
            }
        } catch (err) {
            logger.print('NET ERROR', 'error');
            if(tTitle) tTitle.textContent = "Connection Fail";
        }
    };

    // 5. Shuffle
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

    UI.initialize(Player);

    // AI Button Logic
    const aiBtn = document.getElementById('btn-ai');
    const aiModal = document.getElementById('ai-modal');
    const aiInput = document.getElementById('ai-input');
    const aiSend = document.getElementById('btn-ai-send');
    const aiCancel = document.getElementById('btn-ai-cancel');

    if (aiBtn) {
        aiBtn.onclick = () => {
            aiModal.classList.add('active');
            aiInput.focus();
        };
    }

    if (aiCancel) {
        aiCancel.onclick = () => aiModal.classList.remove('active');
    }

    if (aiSend) {
        aiSend.onclick = async () => {
            const prompt = aiInput.value;
            if (!prompt) return;

            aiModal.classList.remove('active');
            aiInput.value = '';
            
            // Визуальный эффект загрузки
            document.getElementById('track-title').textContent = "NEURAL PROCESSING...";
            document.getElementById('track-artist').textContent = "Связь с ядром Gemini...";
            document.documentElement.style.setProperty('--reactor-color', '#bc13fe'); // Фиолетовый цвет AI

            // Вызов AI
            const playlist = await AI.askAurora(prompt);
            
            if (playlist && playlist.length > 0) {
                // Если треки пришли без ссылок (только названия), 
                // плеер попытается их найти при воспроизведении (нужна доработка player.js)
                // ИЛИ: В рамках MVP мы считаем, что query достаточно
                store.playlist = playlist;
                Player.playTrack(0);
            }
        };
    }
});