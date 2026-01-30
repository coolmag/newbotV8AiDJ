// api.js
// Optimized for Railway - Handles API calls and streaming logic

export class APIError extends Error {
    constructor(message, type = 'network', details = null) {
        super(message);
        this.name = 'APIError';
        this.type = type; 
        this.details = details;
        this.timestamp = new Date().toISOString();
    }
    
    static fromFetchError(error, response = null) {
        if (error.name === 'TypeError' && error.message.includes('fetch')) {
            return new APIError('Сетевая ошибка: проверьте подключение', 'network', { original: error.message });
        }
        
        if (response) {
            switch (response.status) {
                case 404: return new APIError('Ресурс не найден', 'not_found', { status: response.status });
                case 429: return new APIError('Слишком много запросов. Подождите немного.', 'rate_limit', { status: response.status });
                case 500: case 502: case 503: case 504:
                    return new APIError('Сервер временно недоступен', 'server', { status: response.status });
                default: return new APIError(`Ошибка сервера: ${response.status}`, 'server', { status: response.status });
            }
        }
        return new APIError('Неизвестная ошибка', 'unknown', { original: error.message });
    }
    
    getUserMessage() {
        const messages = {
            network: 'Ошибка сети: проверьте подключение к интернету',
            server: 'Сервер временно недоступен. Попробуйте позже.',
            not_found: 'По вашему запросу ничего не найдено',
            rate_limit: 'Слишком много запросов. Подождите 1 минуту.',
            unknown: 'Произошла техническая ошибка'
        };
        return messages[this.type] || messages.unknown;
    }
}

const BASE_URL = window.location.origin;

export const api = {
    getStreamUrl(videoId) {
        return `${BASE_URL}/stream/${videoId}`;
    },

    async search(query) {
        console.log(`[API] Запрос поиска для: ${query}`);
        try {
            const response = await fetch(`${BASE_URL}/api/player/playlist?query=${encodeURIComponent(query)}`);
            
            if (!response.ok) {
                throw APIError.fromFetchError(new Error(`HTTP ${response.status}`), response);
            }
            
            const data = await response.json();
            console.log(`[API] Получено треков: ${data.playlist?.length || 0}`);
            return data.playlist || [];
            
        } catch (error) {
            console.error('[API] Ошибка при поиске:', error);
            if (!(error instanceof APIError)) {
                throw APIError.fromFetchError(error);
            }
            throw error;
        }
    },

    async getRandomTrack() {
        console.log('[API] Запрос случайного трека...');
        try {
            // For now, leverage the existing search endpoint with a generic query
            // In future, a dedicated backend endpoint /api/radio/next might be better
            const randomQueries = ["top hits", "trending songs", "popular music", "random tracks"];
            const query = randomQueries[Math.floor(Math.random() * randomQueries.length)];
            const playlist = await this.search(query);
            if (playlist && playlist.length > 0) {
                return playlist[Math.floor(Math.random() * playlist.length)];
            }
            return null;
        } catch (error) {
            console.error('[API] Ошибка при получении случайного трека:', error);
            if (!(error instanceof APIError)) {
                throw APIError.fromFetchError(error);
            }
            throw error;
        }
    },
    
    async checkHealth() {
        try {
            const response = await fetch(`${BASE_URL}/api/health`, { method: 'HEAD' });
            return {
                ok: response.ok,
                status: response.status,
                statusText: response.statusText
            };
        } catch (error) {
            return {
                ok: false,
                error: new APIError('API недоступен', 'network', { original: error.message })
            };
        }
    }
};