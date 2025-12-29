import { store } from './store.js';
import { Visualizer } from './visualizer.js'; // Импорт для управления FX

const audio = document.getElementById('audio-player');
let onStatusChange = null;
let isBassBoosted = false;

function setupAudioListeners() {
    audio.addEventListener('loadstart', () => reportStatus('loading', 'УСТАНОВКА СОЕДИНЕНИЯ...'));
    audio.addEventListener('waiting', () => reportStatus('loading', 'БУФЕРИЗАЦИЯ...'));
    audio.addEventListener('canplay', () => {
        reportStatus('ready', 'ПОТОК ГОТОВ');
        if (store.isPlaying) audio.play().catch(console.warn);
    });
    audio.addEventListener('play', () => {
        store.isPlaying = true;
        reportStatus('playing', 'ВОСПРОИЗВЕДЕНИЕ');
        document.documentElement.style.setProperty('--reactor-color', '#00f2ff');
    });
    audio.addEventListener('pause', () => {
        store.isPlaying = false;
        reportStatus('paused', 'ПАУЗА');
        document.documentElement.style.setProperty('--reactor-color', '#ff0055');
    });
    audio.addEventListener('error', (e) => {
        reportStatus('error', 'ОШИБКА ПОТОКА. ПЕРЕКЛЮЧЕНИЕ...');
        document.documentElement.style.setProperty('--reactor-color', '#ff0000');
        setTimeout(() => nextTrack(), 2000);
    });
    audio.addEventListener('ended', () => nextTrack());
}

function reportStatus(state, message) { if (onStatusChange) onStatusChange(state, message); }
function setStatusCallback(fn) { onStatusChange = fn; }

async function playTrack(index) {
    if (index < 0 || index >= store.playlist.length) return;
    store.currentTrackIndex = index;
    const track = store.playlist[index];

    audio.pause();
    store.isPlaying = true;
    reportStatus('loading', `ЗАГРУЗКА: ${track.title.toUpperCase().substring(0, 20)}...`);
    document.documentElement.style.setProperty('--reactor-color', '#ffe600');

    audio.src = `/audio/${track.identifier}.mp3`;
    audio.load();
    try { await audio.play(); } catch (e) { if (e.name !== 'AbortError') console.warn("Play interrupted"); }
}

function togglePlay() {
    if (audio.paused) {
        if (store.currentTrackIndex === -1 && store.playlist.length > 0) playTrack(0);
        else audio.play().catch(() => playTrack(store.currentTrackIndex));
    } else { audio.pause(); }
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
    let newTime = audio.duration * pct;
    if (audio.buffered.length > 0) {
        const bufferedEnd = audio.buffered.end(audio.buffered.length - 1);
        if (newTime > bufferedEnd) {
             if (newTime < audio.duration - 5) {
                 newTime = bufferedEnd - 1; 
                 reportStatus('loading', 'БУФЕРИЗАЦИЯ... ПОДОЖДИТЕ');
             }
        }
    }
    audio.currentTime = newTime;
    reportStatus('seeking', `ПЕРЕМОТКА НА ${Math.floor(pct*100)}%`);
}

// --- НОВАЯ ФУНКЦИЯ FX ---
function toggleBassBoost() {
    isBassBoosted = !isBassBoosted;
    Visualizer.setBassBoost(isBassBoosted);
    reportStatus('info', `УСИЛЕНИЕ БАСА: ${isBassBoosted ? 'ВКЛ' : 'ВЫКЛ'}`);
    return isBassBoosted;
}

setupAudioListeners();

export const Player = {
    playTrack, togglePlay, nextTrack, prevTrack, seek, getAudioElement: () => audio, setStatusCallback,
    toggleBassBoost // Экспорт
};