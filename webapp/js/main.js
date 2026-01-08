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
        const logLed = document.getElementById('system-log');
        if (logLed) {
            logLed.textContent = msg;
            logLed.style.color = type === 'error' ? '#ff3333' : '#00f2ff';
        }
    }
};

function toggleLoader(show, text = "LOADING...") {
    const loader = document.getElementById('deck-loader');
    if (!loader) return;
    const txt = loader.querySelector('.loader-text');
    if (show) {
        if (txt) txt.textContent = text;
        loader.classList.add('active');
    } else {
        loader.classList.remove('active');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    logger.init();
    
    // Telegram WebApp Init
    try {
        const tg = window.Telegram?.WebApp;
        if (tg) { 
            tg.expand(); 
            if (tg.isVersionAtLeast && tg.isVersionAtLeast('6.1')) {
                tg.setHeaderColor('#0a0a0f'); 
                tg.setBackgroundColor('#0a0a0f'); 
            }
        }
    } catch (e) {}

    // Status Callback
    Player.setStatusCallback((state, message) => {
        if (state === 'playing') toggleLoader(false);
        
        logger.print(message, state === 'error' ? 'error' : 'info');
        
        const tArtist = document.getElementById('track-artist');
        if (tArtist) {
            if (state === 'loading') { 
                tArtist.textContent = "LOADING..."; 
                tArtist.style.color = '#ffeb3b'; 
            } else if (state === 'playing') {
                const track = store.playlist[store.currentTrackIndex];
                if (track) { 
                    tArtist.textContent = track.artist; 
                    tArtist.style.color = '#333'; 
                }
            }
        }
    });

    const startBtn = document.getElementById('btn-start-system');
    const startOverlay = document.getElementById('start-overlay');
    
    // --- ГЛАВНОЕ ИСПРАВЛЕНИЕ ЗАПУСКА ---
    const handleStart = async () => {
        const audio = Player.getAudioElement();
        
        // 1. Сразу скрываем оверлей, чтобы дать фидбек пользователю
        if (startOverlay) { 
            startOverlay.style.opacity = '0'; 
            setTimeout(() => startOverlay.remove(), 500); 
        }

        // 2. ЖЕСТКАЯ разблокировка аудио-контекста
        try {
            // Создаем контекст визуализатора (он же основной аудио контекст)
            await Visualizer.initialize(audio);
            
            // Если аудио на паузе (а оно на паузе), пытаемся проиграть тишину
            // Это "пинает" движок браузера
            if (audio.paused) {
                audio.play().then(() => {
                    // Если плейлиста нет, ставим на паузу и сбрасываем время
                    if (store.playlist.length === 0) {
                        audio.pause();
                        audio.currentTime = 0;
                    }
                }).catch(err => console.log("Audio kickstart:", err));
            }
        } catch (e) {
            console.error("Audio Context Unlock Failed:", e);
        }
        
        // 3. Загружаем стартовый контент
        window.loadGenreHandler('top 50 global hits');
    };
    
    if (startBtn) {
        // Используем 'click' как самое надежное событие. 
        // Убрали touchstart и preventDefault, так как они могут блокировать AudioContext.
        startBtn.onclick = handleStart;
    }

    window.loadGenreHandler = async (query) => {
        UI.toggleDrawer('genres', false);
        toggleLoader(true, `SCANNING: ${query.toUpperCase()}`);
        
        try {
            const playlist = await fetchPlaylist(query);
            store.playlist = playlist;
            
            if (playlist && playlist.length > 0) { 
                // Небольшая задержка перед стартом, чтобы UI прогрузился
                setTimeout(() => {
                    Player.playTrack(0);
                    toggleLoader(false);
                }, 100);
            } else { 
                toggleLoader(false);
                logger.print('NO TAPE FOUND', 'error'); 
            }
        } catch (err) { 
            toggleLoader(false);
            logger.print('NET ERROR', 'error'); 
        }
    };

    const btnShuffle = document.getElementById('btn-shuffle');
    if (btnShuffle) {
        btnShuffle.onclick = () => {
            if (!store.playlist || store.playlist.length < 2) return;
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
        
        toggleLoader(true, "NEURAL PROCESSING...");
        
        const playlist = await AI.askAurora(prompt);
        toggleLoader(false);
        
        if (playlist && playlist.length > 0) { 
            store.playlist = playlist; 
            Player.playTrack(0); 
        }
    };

    UI.initialize(Player);
});