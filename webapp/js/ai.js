import { fetchPlaylist } from './api.js';
import { store } from './store.js';

const SYNTH = window.speechSynthesis;

export async function askAurora(userPrompt) {
    console.log(`[AI] Request: ${userPrompt}`);
    
    // Показываем, что думаем
    const titleEl = document.getElementById('track-title-scrolling');
    if (titleEl) titleEl.textContent = "AI PROCESSING...";

    try {
        const response = await fetch(`/api/ai/dj?prompt=${encodeURIComponent(userPrompt)}`);
        const data = await response.json();
        
        // 1. ПРОВЕРКА НА ОШИБКИ В ТЕКСТЕ
        let introText = data.dj_intro;
        if (!introText || introText.includes("Error") || introText.includes("404")) {
            // Если ИИ сломался, говорим стандартную фразу
            introText = "Принято. Включаю музыку.";
        }
        
        speak(introText);

        if (data.playlist && data.playlist.length > 0) {
            return data.playlist;
        } else {
            return await fetchPlaylist(userPrompt + " mix");
        }

    } catch (e) {
        console.error("[AI] Error:", e);
        // Fallback голос
        speak("Сигнал нестабилен. Запускаю резервный канал.");
        return await fetchPlaylist(userPrompt + " music");
    }
}

function speak(text) {
    if (!SYNTH) return;
    SYNTH.cancel(); 
    
    const u = new SpeechSynthesisUtterance(text);
    u.lang = 'ru-RU';
    u.rate = 0.95; 
    
    const audio = document.getElementById('audio-player');
    let prevVol = 1.0;
    if (audio) {
        prevVol = audio.volume;
        audio.volume = 0.3;
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

    const voices = SYNTH.getVoices();
    const ruVoice = voices.find(v => v.lang.includes('ru'));
    if (ruVoice) u.voice = ruVoice;

    SYNTH.speak(u);
}
