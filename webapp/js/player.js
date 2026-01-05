import { store } from './store.js';
import { Visualizer } from './visualizer.js';

const audio = document.getElementById('audio-player');
let onStatusChange = null;
let isBassBoosted = false;

function setupAudioContext() {
    if (audio) {
        audio.setAttribute('playsinline', 'true');
        audio.setAttribute('webkit-playsinline', 'true');
        audio.preload = 'auto';
    }
}

function updateReelsState(playing) {
    const reels = document.querySelectorAll('.reel');
    reels.forEach(r => {
        if (playing) r.classList.add('spinning');
        else r.classList.remove('spinning');
    });
    
    const playBtn = document.getElementById('btn-play-pause');
    if (playBtn) {
        if (playing) playBtn.classList.add('active');
        else playBtn.classList.remove('active');
    }
}

function setupAudioListeners() {
    audio.addEventListener('loadstart', () => reportStatus('loading', 'LOADING TAPE...'));
    audio.addEventListener('waiting', () => reportStatus('loading', 'BUFFERING...'));
    audio.addEventListener('canplay', () => {
        reportStatus('ready', 'TAPE READY');
        if (store.isPlaying) safePlay();
    });
    audio.addEventListener('play', () => {
        store.isPlaying = true;
        updateReelsState(true);
        reportStatus('playing', 'PLAYING');
        document.documentElement.style.setProperty('--reactor-color', '#00f2ff'); // Cyan
        updateMediaSession();
    });
    audio.addEventListener('pause', () => {
        store.isPlaying = false;
        updateReelsState(false);
        reportStatus('paused', 'STOPPED');
        document.documentElement.style.setProperty('--reactor-color', '#ff0055'); // Red
    });
    audio.addEventListener('error', (e) => {
        console.error("Audio Error:", e);
        updateReelsState(false);
        reportStatus('error', 'TAPE ERROR');
        document.documentElement.style.setProperty('--reactor-color', '#ff0000');
        setTimeout(() => nextTrack(), 2000);
    });
    audio.addEventListener('ended', () => {
        updateReelsState(false);
        nextTrack();
    });
}

async function safePlay() {
    try {
        await audio.play();
        updateMediaSession();
        updateReelsState(true);
    } catch (e) {
        console.warn("Autoplay blocked:", e);
        store.isPlaying = false;
        updateReelsState(false);
        reportStatus('paused', 'PRESS PLAY');
    }
}

function updateMediaSession() {
    if (!('mediaSession' in navigator)) return;
    const track = store.playlist[store.currentTrackIndex];
    if (!track) return;
    
    const artwork = track.thumbnail_url 
        ? [{ src: track.thumbnail_url, sizes: '512x512', type: 'image/jpeg' }]
        : [{ src: 'https://cdn-icons-png.flaticon.com/512/4430/4430494.png', sizes: '512x512', type: 'image/png' }];

    navigator.mediaSession.metadata = new MediaMetadata({
        title: track.title,
        artist: track.artist,
        album: 'Aurora Deck',
        artwork: artwork
    });

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
    reportStatus('loading', `LOADING: ${track.title.toUpperCase().substring(0, 20)}`);
    document.documentElement.style.setProperty('--reactor-color', '#ffe600'); // Yellow loading
    audio.src = `/audio/${track.identifier}.mp3`;
    updateMediaSession();
    audio.load();
    await safePlay();
}

function togglePlay() {
    if (audio.paused) {
        if (store.currentTrackIndex === -1 && store.playlist.length > 0) playTrack(0);
        else safePlay();
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
    audio.currentTime = audio.duration * pct;
}

function toggleBassBoost() {
    isBassBoosted = !isBassBoosted;
    Visualizer.setBassBoost(isBassBoosted);
    reportStatus('info', `BASS BOOST: ${isBassBoosted ? 'ON' : 'OFF'}`);
    return isBassBoosted;
}

setupAudioContext();
setupAudioListeners();

export const Player = {
    playTrack, togglePlay, nextTrack, prevTrack, seek, getAudioElement: () => audio, setStatusCallback,
    toggleBassBoost
};