/**
 * Модуль для связи с FastAPI бэкендом.
 */
export async function fetchPlaylist(query) {
    console.log(`[API] Запрос плейлиста для: ${query}`);
    try {
        const response = await fetch(`/api/player/playlist?query=${encodeURIComponent(query)}`);
        if (!response.ok) {
            throw new Error(`Network response was not ok: ${response.statusText}`);
        }
        const data = await response.json();
        console.log(`[API] Получено треков: ${data.playlist?.length || 0}`);
        return data.playlist || [];
    } catch (e) {
        console.error('[API] Ошибка при получении плейлиста:', e);
        // Возвращаем пустой массив, чтобы не ломать приложение
        return [];
    }
}
