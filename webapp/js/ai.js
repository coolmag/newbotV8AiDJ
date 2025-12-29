import { store } from './store.js';
import { fetchPlaylist } from './api.js'; // Используем существующий поиск как фоллбэк

const SYNTH = window.speechSynthesis;

// Настройка голоса (пытаемся найти русский)
function getVoice() {
    const voices = SYNTH.getVoices();
    // Ищем Google русский или любой русский
    return voices.find(v => v.lang.includes('ru-RU') && v.name.includes('Google')) 
        || voices.find(v => v.lang.includes('ru')) 
        || voices[0];
}

export async function askAurora(userPrompt) {
    console.log(`[AI] Thinking about: ${userPrompt}`);
    
    try {
        // 1. Запрос к вашему новому бэкенду
        const response = await fetch(`/api/ai/dj?prompt=${encodeURIComponent(userPrompt)}`);
        const data = await response.json();

        if (data.error) throw new Error(data.error);

        // 2. Озвучиваем интро (Voice Over)
        if (data.dj_intro) {
            speak(data.dj_intro);
        }

        // 3. Возвращаем плейлист
        // Важно: Бэкенд вернул "болванки", нам нужно их "зарядить" реальными ссылками
        // В рамках MVP мы можем просто вернуть массив, 
        // а `api.js` должен уметь искать их по очереди, или мы используем `query`
        
        // Для упрощения: если бэкенд вернул query, используем наш старый добрый fetchPlaylist
        // Но чтобы не ждать вечность, берем первый трек и запускаем поиск
        
        // ХАК ДЛЯ MVP: Пока бэкенд не ищет ссылки сам, 
        // мы берем первый трек из рекомендации AI и ищем похожие через старый API.
        // Или, если вы доработали бэкенд поиска, используем data.playlist напрямую.
        
        // Вариант "Умный":
        return data.playlist; 

    } catch (e) {
        console.error("[AI Fail]", e);
        speak("Связь с нейросетью потеряна. Включаю аварийные протоколы.");
        // Фоллбэк на старый поиск
        return await fetchPlaylist(userPrompt);
    }
}

// Функция речи (Ducking - приглушение музыки)
function speak(text) {
    if (!SYNTH) return;
    
    // Отмена предыдущей речи
    SYNTH.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.voice = getVoice();
    utterance.rate = 1.1; // Динамичный темп
    utterance.pitch = 0.9; // Чуть ниже (более "радийный" голос)

    const audio = document.getElementById('audio-player');
    const originalVol = audio.volume;

    utterance.onstart = () => {
        // Плавное приглушение (Ducking)
        audio.dataset.originalVolume = originalVol;
        fadeVolume(audio, 0.2);
    };

    utterance.onend = () => {
        // Возврат громкости
        fadeVolume(audio, parseFloat(audio.dataset.originalVolume || 1));
    };

    SYNTH.speak(utterance);
}

function fadeVolume(audio, target) {
    const step = 0.05;
    const interval = 50;
    
    const fade = setInterval(() => {
        if (Math.abs(audio.volume - target) < step) {
            audio.volume = target;
            clearInterval(fade);
        } else if (audio.volume > target) {
            audio.volume -= step;
        } else {
            audio.volume += step;
        }
    }, interval);
}