import { fetchPlaylist } from './api.js';
import { store } from './store.js';

const SYNTH = window.speechSynthesis;

export async function askAurora(userPrompt) {
    console.log(`[AI] Request: ${userPrompt}`);
    
    const titleEl = document.getElementById('track-title-scrolling');
    if (titleEl) titleEl.textContent = "AI PROCESSING...";

    try {
        const response = await fetch(`/api/ai/dj?prompt=${encodeURIComponent(userPrompt)}`);
        
        if (!response.ok) throw new Error("AI Offline");
        
        const data = await response.json();
        
        // ОЗВУЧКА ТОЛЬКО ЕСЛИ ЕСТЬ ТЕКСТ И ЭТО НЕ ОШИБКА
        if (data.dj_intro && data.dj_intro.length > 2 && !data.dj_intro.includes("Error")) {
            speak(data.dj_intro);
        }

        if (data.playlist && data.playlist.length > 0) {
            return data.playlist;
        } else {
            return await fetchPlaylist(userPrompt + " mix");
        }

    } catch (e) {
        console.error("[AI] Error:", e);
        // Молчаливый фолбэк
        return await fetchPlaylist(userPrompt + " music");
    }
}

function speak(text) {
    if (!SYNTH) return;
    SYNTH.cancel(); 
    
    const u = new SpeechSynthesisUtterance(text);
    u.lang = 'ru-RU';
    u.rate = 0.9; // Чуть медленнее, чтобы было разборчиво
    u.pitch = 1.0; 

    // Приглушение музыки
    const audio = document.getElementById('audio-player');
    let prevVol = 1.0;
    if (audio) {
        prevVol = audio.volume;
        audio.volume = 0.3; // Тише
    }

    u.onend = () => { 
        if (audio) {
            // Плавный возврат громкости
            let v = 0.3;
            const fadeIn = setInterval(() => {
                if (v < prevVol) {
                    v += 0.1;
                    audio.volume = Math.min(v, 1.0);
                } else clearInterval(fadeIn);
            }, 100);
        }
    };

    // Поиск русского голоса
    const voices = SYNTH.getVoices();
    // Предпочтение Google голосам
    const ruVoice = voices.find(v => v.lang.includes('ru') && v.name.includes('Google'));
    // Если нет, любой русский
    const anyRu = voices.find(v => v.lang.includes('ru'));
    
    if (ruVoice) u.voice = ruVoice;
    else if (anyRu) u.voice = anyRu;

    SYNTH.speak(u);
}