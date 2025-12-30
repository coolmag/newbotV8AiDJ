import { fetchPlaylist } from './api.js';
const SYNTH = window.speechSynthesis;

export async function askAurora(userPrompt) {
    console.log(`[AI] Input: ${userPrompt}`);
    const intros = ["Принято. Ищу лучшие треки.", "Запускаю поиск.", "Отличный выбор.", "Аврора на связи."];
    const randomIntro = intros[Math.floor(Math.random() * intros.length)];
    speak(randomIntro);
    
    // Используем простой поиск, так как это надежнее и бесплатно
    return await fetchPlaylist(userPrompt + " mix");
}

function speak(text) {
    if (!SYNTH) return;
    SYNTH.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = 'ru-RU';
    u.rate = 1.1; 
    const audio = document.getElementById('audio-player');
    const vol = audio.volume;
    audio.volume = 0.2;
    u.onend = () => { audio.volume = vol; };
    const voices = SYNTH.getVoices();
    const ruVoice = voices.find(v => v.lang.includes('ru'));
    if (ruVoice) u.voice = ruVoice;
    SYNTH.speak(u);
}