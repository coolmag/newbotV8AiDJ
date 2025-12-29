import { fetchPlaylist } from './api.js';

const SYNTH = window.speechSynthesis;

export async function askAurora(userPrompt) {
    console.log(`[AI] Input: ${userPrompt}`);
    
    // 1. Говорим фразу (Локально, без сервера)
    const intros = [
        "Принято. Ищу лучшие треки.",
        "Запускаю поиск по базе данных.",
        "Отличный запрос. Погнали.",
        "Аврора на связи. Выполняю."
    ];
    const randomIntro = intros[Math.floor(Math.random() * intros.length)];
    speak(randomIntro);

    // 2. Ищем музыку через обычный поиск (Самый надежный способ сейчас)
    // Мы временно отключили запрос к /api/ai/dj, чтобы не было ошибки "Связь потеряна"
    return await fetchPlaylist(userPrompt + " mix");
}

function speak(text) {
    if (!SYNTH) return;
    SYNTH.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = 'ru-RU'; // Пытаемся говорить по-русски
    u.rate = 1.1; 
    
    // Приглушение музыки
    const audio = document.getElementById('audio-player');
    const vol = audio.volume;
    audio.volume = 0.2;
    u.onend = () => { audio.volume = vol; };
    
    // Пытаемся найти русский голос
    const voices = SYNTH.getVoices();
    const ruVoice = voices.find(v => v.lang.includes('ru'));
    if (ruVoice) u.voice = ruVoice;

    SYNTH.speak(u);
}