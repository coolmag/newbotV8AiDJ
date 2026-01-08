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
        
        // ОЗВУЧКА (Всегда, если есть текст)
        if (data.dj_intro) {
            speak(data.dj_intro);
        }

        if (data.playlist && data.playlist.length > 0) {
            return data.playlist;
        } else {
            return await fetchPlaylist(userPrompt + " mix");
        }

    } catch (e) {
        console.error("[AI] Error:", e);
        speak("Сигнал нестабилен. Запускаю поиск.");
        return await fetchPlaylist(userPrompt + " music");
    }
}

function speak(text) {
    if (!SYNTH) return;
    SYNTH.cancel(); 
    
    const u = new SpeechSynthesisUtterance(text);
    u.lang = 'ru-RU';
    u.rate = 1.0;  // Нормальная скорость
    u.pitch = 1.1; // Чуть выше (женственнее)

    const audio = document.getElementById('audio-player');
    let prevVol = 1.0;
    if (audio) {
        prevVol = audio.volume;
        audio.volume = 0.2; // Сильнее приглушаем музыку
    }

    u.onend = () => { 
        if (audio) {
            let v = 0.2;
            const fadeIn = setInterval(() => {
                if (v < prevVol) {
                    v += 0.1;
                    audio.volume = Math.min(v, 1.0);
                } else clearInterval(fadeIn);
            }, 100);
        }
    };

    const voices = SYNTH.getVoices();
    const ruVoice = voices.find(v => v.lang.includes('ru') && (v.name.includes('Google') || v.name.includes('Female')));
    if (ruVoice) u.voice = ruVoice;

    SYNTH.speak(u);
}