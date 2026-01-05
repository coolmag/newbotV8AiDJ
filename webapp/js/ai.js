import { fetchPlaylist } from './api.js';
import { store } from './store.js';

const SYNTH = window.speechSynthesis;

export async function askAurora(userPrompt) {
    console.log(`[AI] Neural Request: ${userPrompt}`);
    
    // Визуальный эффект "Думает"
    const titleEl = document.getElementById('track-title-scrolling');
    if (titleEl) titleEl.textContent = "NEURAL PROCESSING...";

    try {
        // 1. Реальный запрос к AI DJ на бэкенде
        const response = await fetch(`/api/ai/dj?prompt=${encodeURIComponent(userPrompt)}`);
        
        if (!response.ok) throw new Error("AI Server Offline");
        
        const data = await response.json();
        
        // 2. Озвучка ответа (DJ Intro)
        if (data.dj_intro) {
            speak(data.dj_intro);
        }

        // 3. Возвращаем плейлист
        if (data.playlist && data.playlist.length > 0) {
            return data.playlist;
        } else {
            // Фолбэк, если AI не нашел треки
            speak("Сигнал потерян. Включаю резервный канал.");
            return await fetchPlaylist(userPrompt + " mix");
        }

    } catch (e) {
        console.error("[AI] Error:", e);
        // Если сервер лежит, работаем по старинке
        return await fetchPlaylist(userPrompt + " music");
    }
}

function speak(text) {
    if (!SYNTH) return;
    SYNTH.cancel(); // Остановить предыдущую речь
    
    const u = new SpeechSynthesisUtterance(text);
    u.lang = 'ru-RU'; // Русский голос
    u.rate = 1.0; 
    u.pitch = 0.9; // Чуть ниже, более "роботизированно"

    // Приглушаем музыку во время речи
    const audio = document.getElementById('audio-player');
    let prevVol = 1.0;
    if (audio) {
        prevVol = audio.volume;
        // Плавное затухание
        const fadeOut = setInterval(() => {
            if (audio.volume > 0.2) audio.volume -= 0.1;
            else clearInterval(fadeOut);
        }, 50);
    }

    u.onend = () => { 
        // Возвращаем громкость
        if (audio) {
            const fadeIn = setInterval(() => {
                if (audio.volume < prevVol) audio.volume += 0.1;
                else clearInterval(fadeIn);
            }, 50);
        }
    };

    // Пытаемся найти женский русский голос (Google Русский / Microsoft Irina)
    const voices = SYNTH.getVoices();
    const ruVoice = voices.find(v => v.lang.includes('ru') && (v.name.includes('Google') || v.name.includes('Female')));
    if (ruVoice) u.voice = ruVoice;

    SYNTH.speak(u);
}