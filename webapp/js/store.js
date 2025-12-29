/**
 * Реактивное хранилище состояния "Aurora".
 * UI будет обновляться при изменении этих значений.
 */
const state = {
    isPlaying: false,
    currentTrackIndex: -1,
    playlist: [],
    currentGenre: 'Aurora',
};

const listeners = {};

function subscribe(property, callback) {
    if (!listeners[property]) {
        listeners[property] = [];
    }
    listeners[property].push(callback);
}

function notify(property, value) {
    if (listeners[property]) {
        listeners[property].forEach(callback => callback(value));
    }
}

const handler = {
    set(target, property, value) {
        if (target[property] !== value) {
            target[property] = value;
            notify(property, value);
        }
        return true;
    }
};

const store = new Proxy(state, handler);

export { store, subscribe };
