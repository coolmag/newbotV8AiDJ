import { store } from './store.js';
import { Visualizer } from './visualizer.js';

const audio = document.getElementById('audio-player');
let onStatusChange = null;
let isBassBoosted = false;

// --- НАСТРОЙКА ДЛЯ ФОНОВОГО РЕЖИМА (iOS/Android) ---
function setupAudioContext() {
    // Важно для iOS: разрешаем проигрывание в беззвучном режиме
    if (audio) {
        audio.setAttribute('playsinline', 'true');
        audio.setAttribute('webkit-playsinline', 'true');
        audio.preload = 'auto';
    }
}

function setupAudioListeners() {
    audio.addEventListener('loadstart', () => reportStatus('loading', 'УСТАНОВКА СОЕДИНЕНИЯ...'));
    audio.addEventListener('waiting', () => reportStatus('loading', 'БУФЕРИЗАЦИЯ...'));
    audio.addEventListener('canplay', () => {
        reportStatus('ready', 'ПОТОК ГОТОВ');
        if (store.isPlaying) {
            safePlay();
        }
    });
    audio.addEventListener('play', () => {
        store.isPlaying = true;
        reportStatus('playing', 'ВОСПРОИЗВЕДЕНИЕ');
        document.documentElement.style.setProperty('--reactor-color', '#00f2ff');
        updateMediaSession(); // Обновляем шторку
    });
    audio.addEventListener('pause', () => {
        store.isPlaying = false;
        reportStatus('paused', 'ПАУЗА');
        document.documentElement.style.setProperty('--reactor-color', '#ff0055');
        // Не обновляем сессию тут, чтобы шторка не пропадала
    });
    audio.addEventListener('error', (e) => {
        console.error("Audio Error:", e);
        reportStatus('error', 'ОШИБКА ПОТОКА. ПЕРЕКЛЮЧЕНИЕ...');
        document.documentElement.style.setProperty('--reactor-color', '#ff0000');
        setTimeout(() => nextTrack(), 2000);
    });
    audio.addEventListener('ended', () => nextTrack());
    
    // Поддержка системных прерываний (звонок, Siri)
    audio.addEventListener('pause', () => {
        // Если это не мы поставили на паузу (а система), обновляем UI
        if (store.isPlaying && audio.paused) {
            store.isPlaying = false;
        }
    });
}

// --- БЕЗОПАСНЫЙ ЗАПУСК ---
async function safePlay() {
    try {
        await audio.play();
        updateMediaSession();
    } catch (e) {
        console.warn("Autoplay blocked or interrupted:", e);
        // Если iOS заблокировал автоплей, ждем клика
        store.isPlaying = false;
        reportStatus('paused', 'НАЖМИТЕ PLAY');
    }
}

// --- MEDIA SESSION API (Управление с заблокированного экрана) ---
function updateMediaSession() {
    if (!('mediaSession' in navigator)) return;

    const track = store.playlist[store.currentTrackIndex];
    if (!track) return;

    // 1. Метаданные (Обложка и текст на экране блокировки)
    navigator.mediaSession.metadata = new MediaMetadata({
        title: track.title,
        artist: track.artist,
        album: 'Aurora AI Radio',
        artwork: [
            { src: 'https://cdn-icons-png.flaticon.com/512/4430/4430494.png', sizes: '512x512', type: 'image/png' }
            // Можно добавить реальную обложку трека, если она есть в track.thumbnail_url
        ]
    });

    // 2. Обработчики кнопок (Lock Screen Controls)
    const handlers = [
        ['play', () => { store.isPlaying = true; safePlay(); }],
        ['pause', () => { store.isPlaying = false; audio.pause(); }],
        ['previoustrack', () => prevTrack()],
        ['nexttrack', () => nextTrack()],
        ['seekto', (details) => { audio.currentTime = details.seekTime; }],
    ];

    for (const [action, handler] of handlers) {
        try { navigator.mediaSession.setActionHandler(action, handler); } catch (e) {}
    }
}

function reportStatus(state, message) { if (onStatusChange) onStatusChange(state, message); }
function setStatusCallback(fn) { onStatusChange = fn; }

async function playTrack(index) {
    if (index < 0 || index >= store.playlist.length) return;
    store.currentTrackIndex = index;
    const track = store.playlist[index];

    store.isPlaying = true;
    reportStatus('loading', `ЗАГРУЗКА: ${track.title.toUpperCase().substring(0, 20)}...`);
    document.documentElement.style.setProperty('--reactor-color', '#ffe600');

    // Формируем URL
    audio.src = `/audio/${track.identifier}.mp3`;
    
    // Обновляем шторку СРАЗУ, чтобы iOS понял, что мы переключили трек
    updateMediaSession();
    
    audio.load();
    await safePlay();
}

function togglePlay() {
    if (audio.paused) {
        if (store.currentTrackIndex === -1 && store.playlist.length > 0) playTrack(0);
        else safePlay();
    } else { 
        audio.pause(); 
    }
}

function nextTrack() {
    let next = store.currentTrackIndex + 1;
    if (next >= store.playlist.length) next = 0;
    playTrack(next);
}

function prevTrack() {
    let prev = store.currentTrackIndex - 1;
    if (prev < 0) prev = store.playlist.length - 1;
    playTrack(prev);
}

function seek(pct) {
    if (!audio.duration) return;
    audio.currentTime = audio.duration * pct;
}

function toggleBassBoost() {
    isBassBoosted = !isBassBoosted;
    Visualizer.setBassBoost(isBassBoosted);
    reportStatus('info', `УСИЛЕНИЕ БАСА: ${isBassBoosted ? 'ВКЛ' : 'ВЫКЛ'}`);
    return isBassBoosted;
}

setupAudioContext();
setupAudioListeners();

export const Player = {
    playTrack, togglePlay, nextTrack, prevTrack, seek, getAudioElement: () => audio, setStatusCallback,
    toggleBassBoost
};