const tg = window.Telegram?.WebApp;
const isSupported = tg && tg.HapticFeedback && tg.isVersionAtLeast && tg.isVersionAtLeast('6.1');

export function impact(style = 'light') {
    if (isSupported) { try { tg.HapticFeedback.impactOccurred(style); } catch(e){} }
}

export function notification(type = 'success') {
    if (isSupported) { try { tg.HapticFeedback.notificationOccurred(type); } catch(e){} }
}