/**
 * Модуль для управления тактильной обратной связью (вибрацией)
 * Safe Version: Checks for API support explicitly.
 */

// Безопасное получение объекта WebApp
const tg = window.Telegram?.WebApp;

// Проверяем, поддерживается ли метод (нужна версия бота 6.1+)
const isSupported = tg && tg.HapticFeedback && tg.isVersionAtLeast && tg.isVersionAtLeast('6.1');

export function impact(style = 'light') {
    if (isSupported) {
        try {
            tg.HapticFeedback.impactOccurred(style);
        } catch (e) {
            // Silently fail if something goes wrong
        }
    }
}

export function notification(type = 'success') {
    if (isSupported) {
        try {
            tg.HapticFeedback.notificationOccurred(type);
        } catch (e) {
             // Silently fail
        }
    }
}