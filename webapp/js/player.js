// player.js - Optimized for Railway
import { store } from './store.js';
import { api } from './api.js';
import { ui } from './ui.js';
import { visualizer } from './visualizer.js';

class Player {
    constructor() {
        this.audio = new Audio();
        this.isPlaying = false;
        this.currentTrackId = null;
        this.loading = false;
        
        // Очередь воспроизведения на клиенте
        this.queue = [];
        this.currentIndex = -1;

        this.setupAudioListeners();
        this._playDebounced = this._debounce(this._actualPlay.bind(this), 300); // 300ms debounce
    }

    setupAudioListeners() {
        this.audio.addEventListener('ended', () => this.next());
        
        this.audio.addEventListener('timeupdate', () => {
            ui.updateProgress(this.audio.currentTime, this.audio.duration);
        });

        this.audio.addEventListener('canplay', () => {
            this.loading = false;
            ui.setLoading(false);
            if (this.isPlaying) this.audio.play().catch(e => console.error("Audio play failed after canplay:", e));
        });
        
        this.audio.addEventListener('error', (e) => {
             console.error("Audio Error:", e);
             this.loading = false;
             ui.setLoading(false);
             ui.showToast("Ошибка воспроизведения. Пробую следующий...", "error");
             setTimeout(() => this.next(), 2000);
        });
    }

    _debounce(func, delay) {
        let timeout;
        return function(...args) {
            const context = this;
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(context, args), delay);
        };
    }

    async _actualPlay(track) {
        if (!track) return;

        // Если это тот же трек, просто переключаем паузу
        if (this.currentTrackId === track.id) {
            this.togglePlay();
            return;
        }

        // Защита: Если уже идет загрузка другого трека - отменяем/ждем
        if (this.loading) {
            this.audio.pause();
            this.audio.src = ""; // Stop current loading
        }

        this.currentTrackId = track.id;
        this.loading = true;
        ui.setLoading(true);
        ui.updatePlayerInfo(track);
        
        // Обновляем UI
        this.isPlaying = true;
        ui.updatePlayButton(true);

        try {
            // 1. Получаем ссылку на поток
            // Важно: api.getStreamUrl не должен качать файл! 
            // Он должен возвращать ссылку /api/stream/ID
            const streamUrl = api.getStreamUrl(track.id);
            
            // 2. Устанавливаем источник. Браузер сам начнет буферизацию.
            this.audio.src = streamUrl;
            this.audio.crossOrigin = "anonymous"; // Для визуализатора
            
            // Запускаем визуализатор
            visualizer.connect(this.audio);

            await this.audio.play();
            
            // Обновляем глобальный стор
            store.setCurrentTrack(track);

        } catch (error) {
            console.error('Play error:', error);
            ui.showToast("Ошибка сервера. Попробуйте позже.", "error");
            this.loading = false;
            ui.setLoading(false);
            this.isPlaying = false;
            ui.updatePlayButton(false);
        }
    }

    play(track) {
        this._playDebounced(track);
    }

    togglePlay() {
        if (this.audio.paused) {
            this.audio.play().catch(e => console.error("Audio play failed on togglePlay:", e));
            this.isPlaying = true;
        } else {
            this.audio.pause();
            this.isPlaying = false;
        }
        ui.updatePlayButton(this.isPlaying);
    }

    next() {
        // Логика переключения (берем из store или локальной очереди)
        const nextTrack = store.getNextTrack();
        if (nextTrack) {
            this.play(nextTrack);
        } else {
            // Если треки кончились - можно запросить "Радио" у сервера
            this.requestRadioNext();
        }
    }

    prev() {
        const prevTrack = store.getPrevTrack();
        if (prevTrack) this.play(prevTrack);
    }
    
    // Запрос к серверу, чтобы сгенерировать следующий трек (как в боте)
    async requestRadioNext() {
        ui.showToast("Ищу музыку...", "info");
        try {
            // Тут можно дернуть ручку /api/radio/next
            // Пока просто берем случайный из каталога
            const randomTrack = await api.getRandomTrack(); 
            if (randomTrack) this.play(randomTrack);
        } catch (e) {
            console.error(e);
            ui.showToast("Не удалось найти случайный трек.", "error");
        }
    }

    setVolume(value) {
        this.audio.volume = value;
    }
    
    seek(percent) {
        if (this.audio.duration) {
            this.audio.currentTime = this.audio.duration * percent;
        }
    }
}

export const player = new Player();